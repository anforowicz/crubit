#!/usr/bin/env python3
# Part of the Crubit project, under the Apache License v2.0 with LLVM
# Exceptions. See /LICENSE for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Locates Bazel build artifacts and generates environment variables for Cargo build."""

import os
import subprocess
import sys

from generate_proto_headers import generate_protobuf_headers

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))


def log(msg):
    print(f"--- {msg}", flush=True)

def fail(msg):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def build_bazel_dependencies():
    """Queries and builds necessary C++ dependencies in Bazel."""
    log("Querying and building C++ dependencies (ir_from_cc, Abseil, Clang, Protobuf, protoc)...")
    query_expr = (
        "kind(cc_library, "
        "deps(//rs_bindings_from_cc:ir_from_cc) union "
        "deps(@abseil-cpp//absl/flags:parse) union "
        "deps(@protobuf//src/google/protobuf:protobuf)"
        ") union set(@protobuf//:protoc //rs_bindings_from_cc:ir_from_cc)"
    )
    try:
        raw_targets = subprocess.check_output(["bazelisk", "query", query_expr], text=True).splitlines()
        targets = [
            t.strip() for t in raw_targets
            if t.strip()
            and not t.startswith(("@bazel_tools//", "@rules_cc//"))
            and "windows" not in t
            and "win32" not in t
        ]
        log(f"Building {len(targets)} Bazel targets...")
        subprocess.check_call(["bazelisk", "build"] + targets)
    except Exception as e:
        fail(f"Failed to query or build Bazel dependencies: {e}")


def resolve_repo_dir(target_label):
    """Resolves the external repo directory for a target label using bazelisk query."""
    try:
        loc = subprocess.check_output(
            ["bazelisk", "query", target_label, "--output=location"],
            text=True
        ).splitlines()[0]
        parts = loc.split(":")
        path = parts[0]
        external_idx = path.find("/external/")
        if external_idx == -1:
            return None
        after_external = path[external_idx + len("/external/"):]
        repo_name = after_external.split("/")[0]
        external_dir = path[:external_idx + len("/external")]
        return os.path.join(external_dir, repo_name)
    except Exception as e:
        print(f"Warning: Failed to resolve repo dir for {target_label}: {e}", file=sys.stderr)
        return None


def find_llvm_generated_headers(resolved_llvm_dirname):
    """Finds LLVM generated header directory inside bazel-out."""
    bazel_out = "bazel-out"
    if not os.path.exists(bazel_out):
        return None

    for d in os.listdir(bazel_out):
        if d.endswith("-fastbuild") or d.endswith("-opt"):
            candidate = os.path.join(bazel_out, d, "bin", "external", resolved_llvm_dirname)
            if os.path.isdir(candidate):
                log(f"Found LLVM generated headers at: {candidate}")
                return candidate
    return None


def find_hermetic_toolchain(external_dir):
    """Finds hermetic Clang/LLVM toolchain binaries and library directories."""
    if not os.path.isdir(external_dir):
        return None

    for d in os.listdir(external_dir):
        if "llvm_toolchain" in d:
            full_path = os.path.join(external_dir, d)
            if os.path.isdir(full_path):
                clang_path = os.path.join(full_path, "bin", "clang")
                clang_xx_path = os.path.join(full_path, "bin", "clang++")
                ar_path = os.path.join(full_path, "bin", "llvm-ar")
                if os.path.exists(clang_path) and os.path.exists(clang_xx_path) and os.path.exists(ar_path):
                    lib_base = os.path.join(full_path, "lib")
                    hermetic_lib_dir = None
                    if os.path.isdir(lib_base):
                        for sub in os.listdir(lib_base):
                            sub_path = os.path.join(lib_base, sub)
                            if os.path.isdir(sub_path) and ("linux" in sub or "darwin" in sub or "apple" in sub):
                                hermetic_lib_dir = os.path.abspath(sub_path)
                                break
                        if not hermetic_lib_dir:
                            hermetic_lib_dir = os.path.abspath(lib_base)

                    return {
                        "clang": os.path.abspath(clang_path),
                        "clang_xx": os.path.abspath(clang_xx_path),
                        "llvm_ar": os.path.abspath(ar_path),
                        "lib_dir": hermetic_lib_dir,
                    }
    return None


def merge_archives(llvm_ar_path, output_archive, input_dirs):
    """Merges all .a static library files in input_dirs into output_archive using llvm-ar MRI script."""
    if os.path.exists(output_archive):
        os.remove(output_archive)

    input_archives = []
    for d in input_dirs:
        if os.path.exists(d):
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith(".a"):
                        input_archives.append(os.path.abspath(os.path.join(root, f)))

    mri_lines = [f"CREATE {output_archive}"]
    for lib in input_archives:
        mri_lines.append(f"ADDLIB {lib}")
    mri_lines.append("SAVE")
    mri_lines.append("END")

    mri_script = "\n".join(mri_lines) + "\n"

    log(f"Merging {len(input_archives)} archives into {output_archive}...")
    try:
        process = subprocess.Popen(
            [llvm_ar_path, "-M"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=mri_script)
        if process.returncode != 0:
            fail(f"llvm-ar failed with exit code {process.returncode}\nStderr: {stderr}")
        log("Merge successful!")
    except Exception as e:
        fail(f"Failed to run llvm-ar: {e}")


def write_env_config(bazel_outputs_dir, env_vars):
    """Writes bazel-env.sh and updates GITHUB_ENV if running in GitHub Actions."""
    env_sh_path = os.path.join(bazel_outputs_dir, "bazel-env.sh")
    with open(env_sh_path, "w") as f:
        f.write("# Generated by setup_bazel_env.py\n")
        for k, v in env_vars.items():
            f.write(f"export {k}=\"{v}\"\n")

    log(f"Saved Bazel environment setup to {env_sh_path}")

    github_env_path = os.environ.get("GITHUB_ENV")
    if github_env_path:
        with open(github_env_path, "a") as f:
            for k, v in env_vars.items():
                f.write(f"{k}={v}\n")
        log(f"Saved environment variables directly to GitHub Actions environment: {github_env_path}")


def main():
    os.chdir(REPO_ROOT)

    # 1. Build C++ dependencies in Bazel
    build_bazel_dependencies()

    # 2. Discover Bazel external directory
    try:
        output_base = subprocess.check_output(["bazelisk", "info", "output_base"], text=True).strip()
        external_dir = os.path.abspath(os.path.join(output_base, "external"))
    except Exception as e:
        fail(f"Failed to get Bazel output_base: {e}")
    log(f"Using Bazel external dir: {external_dir}")

    bin_external_base = "bazel-bin/external"
    bazel_outputs_dir = os.path.abspath(os.path.join(REPO_ROOT, "target", "bazel_outputs"))
    os.makedirs(bazel_outputs_dir, exist_ok=True)

    # 3. LLVM/Clang paths
    llvm_proj_dir = resolve_repo_dir("@llvm-project//llvm:Support")
    if not llvm_proj_dir:
        fail("Could not find llvm directory using bazelisk query")
    resolved_llvm_dirname = os.path.basename(llvm_proj_dir)
    log(f"Found LLVM project source at: {llvm_proj_dir}")

    gen_llvm_proj_dir = find_llvm_generated_headers(resolved_llvm_dirname)
    clang_include_paths = [
        os.path.abspath(os.path.join(llvm_proj_dir, "clang", "include")),
        os.path.abspath(os.path.join(llvm_proj_dir, "llvm", "include")),
    ]
    if gen_llvm_proj_dir:
        clang_include_paths.extend([
            os.path.abspath(os.path.join(gen_llvm_proj_dir, "clang", "include")),
            os.path.abspath(os.path.join(gen_llvm_proj_dir, "llvm", "include")),
        ])
    clang_include_paths.append(os.path.abspath("bazel-bin"))

    bin_llvm_proj_dir = os.path.join(bin_external_base, resolved_llvm_dirname)
    clang_lib_paths = []
    if os.path.isdir(bin_llvm_proj_dir):
        clang_lib_paths = [
            os.path.abspath(os.path.join(bin_llvm_proj_dir, "clang")),
            os.path.abspath(os.path.join(bin_llvm_proj_dir, "llvm")),
        ]

    # 4. Abseil paths
    absl_src_dir = resolve_repo_dir("@abseil-cpp//absl/base:base")
    if not absl_src_dir:
        fail("Could not find abseil-cpp directory using bazelisk query")
    log(f"Found Abseil source at: {absl_src_dir}")
    resolved_absl_dirname = os.path.basename(absl_src_dir)
    absl_include_paths = [os.path.abspath(absl_src_dir)]

    bin_absl_dir = os.path.join(bin_external_base, resolved_absl_dirname)
    if not os.path.isdir(bin_absl_dir):
        bin_absl_dir = os.path.join(bin_external_base, "abseil-cpp+")
    absl_lib_base = os.path.join(bin_absl_dir, "absl")

    # 5. Protobuf paths
    protobuf_dir = resolve_repo_dir("@protobuf//:protobuf")
    protoc_path = None
    protobuf_lib_base = None
    if protobuf_dir:
        resolved_protobuf_dirname = os.path.basename(protobuf_dir)
        bin_protobuf_dir = os.path.join(bin_external_base, resolved_protobuf_dirname)
        protobuf_lib_base = bin_protobuf_dir
        candidate_protoc = os.path.abspath(os.path.join(bin_protobuf_dir, "protoc"))
        if os.path.exists(candidate_protoc):
            protoc_path = candidate_protoc

    if not protoc_path or not os.path.exists(protoc_path):
        fail(f"protoc not found at expected path: {protoc_path}")

    # 6. Pre-generate proto headers
    proto_include_dir = os.path.join(bazel_outputs_dir, "include")
    log(f"Pre-generating C++ Protobuf headers into {proto_include_dir}...")
    generate_protobuf_headers(protoc_path, proto_include_dir, REPO_ROOT)


    # 7. Hermetic Toolchain
    toolchain = find_hermetic_toolchain(external_dir)
    if not toolchain:
        fail("Hermetic toolchain or llvm-ar not found in toolchains_llvm.")

    # 8. Merge static libraries into monolithic archives
    absl_monolithic_path = os.path.join(bazel_outputs_dir, "libabsl_monolithic.a")
    merge_archives(toolchain["llvm_ar"], absl_monolithic_path, [absl_lib_base])

    clang_monolithic_path = os.path.join(bazel_outputs_dir, "libclang_monolithic.a")
    merge_archives(toolchain["llvm_ar"], clang_monolithic_path, clang_lib_paths)

    if protobuf_lib_base:
        protobuf_monolithic_dir = os.path.join(bazel_outputs_dir, "protobuf")
        os.makedirs(protobuf_monolithic_dir, exist_ok=True)
        protobuf_monolithic_path = os.path.join(protobuf_monolithic_dir, "libprotobuf.a")
        merge_archives(toolchain["llvm_ar"], protobuf_monolithic_path, [protobuf_lib_base])

    # 9. Environment variables
    env_vars = {
        "CLANG_INCLUDE_PATH": ",".join(clang_include_paths),
        "CLANG_LIB_STATIC_PATH": bazel_outputs_dir,
        "ABSL_INCLUDE_PATH": ",".join(absl_include_paths),
        "ABSL_LIB_STATIC_PATH": bazel_outputs_dir,
        "PROTOC": protoc_path,
    }
    if protobuf_dir:
        env_vars["PROTOBUF_INCLUDE_PATH"] = ",".join([
            proto_include_dir,
            os.path.abspath(os.path.join(protobuf_dir, "src")),
            os.path.abspath(os.path.join(protobuf_dir, "third_party", "utf8_range")),
        ])
        env_vars["PROTOBUF_LIB_STATIC_PATH"] = os.path.join(bazel_outputs_dir, "protobuf")

    if toolchain:
        log(f"Found hermetic Clang: {toolchain['clang']}")
        env_vars["CC"] = toolchain["clang"]
        env_vars["CXX"] = toolchain["clang_xx"]
        env_vars["CXXFLAGS"] = "-stdlib=libc++"

        hermetic_clang_dir = os.path.dirname(toolchain["clang"])
        rustflags = [
            f"-C linker={toolchain['clang']}",
            f"-C link-arg=-fuse-ld={os.path.join(hermetic_clang_dir, 'ld.lld')}",
            "-C link-arg=-stdlib=libc++",
            "-C link-arg=-lc++",
            "-C link-arg=-lc++abi",
            "-C link-arg=-lunwind",
            "-C link-arg=-lzstd",
        ]
        if toolchain["lib_dir"]:
            log(f"Found hermetic Lib dir: {toolchain['lib_dir']}")
            rustflags.append(f"-C link-arg=-L{toolchain['lib_dir']}")
            rustflags.append(f"-C link-arg=-Wl,-rpath,{toolchain['lib_dir']}")
            rustflags.append("-C link-arg=-Wl,--disable-new-dtags")

        env_vars["RUSTFLAGS"] = " ".join(rustflags)

    write_env_config(bazel_outputs_dir, env_vars)

    print("\nTo configure your environment, run:")
    print(f"source {os.path.relpath(os.path.join(bazel_outputs_dir, 'bazel-env.sh'), REPO_ROOT)}")

if __name__ == "__main__":
    main()

