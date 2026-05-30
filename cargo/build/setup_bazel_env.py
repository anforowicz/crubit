#!/usr/bin/env python3
# Part of the Crubit project, under the Apache License v2.0 with LLVM
# Exceptions. See /LICENSE for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Locates Bazel build artifacts and generates environment variables for Cargo build."""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

def log(msg):
    print(f"--- {msg}", flush=True)

def fail(msg):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def merge_archives(llvm_ar_path, output_archive, input_dirs):
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

def main():
    os.chdir(REPO_ROOT)

    # 1. Verify Bazel symlinks exist
    required_symlinks = ["bazel-bin", "bazel-crubit", "bazel-out"]
    for sym in required_symlinks:
        if not os.path.exists(sym):
            fail(f"Symlink '{sym}' not found in repo root.\nPlease run 'bazelisk build rs_bindings_from_cc:rs_bindings_from_cc_main' first.")

    # 2. LLVM/Clang paths
    external_dir = os.path.abspath(os.path.join(REPO_ROOT, "bazel-crubit", "external"))
    log(f"Using Bazel external dir: {external_dir}")

    llvm_proj_dir = None
    resolved_llvm_dirname = None
    for d in os.listdir(external_dir):
        if "llvm-project" in d:
            full_path = os.path.join(external_dir, d)
            if os.path.isdir(full_path):
                llvm_proj_dir = full_path
                resolved_llvm_dirname = d
                break

    if not llvm_proj_dir:
        fail("Could not find llvm-project directory in bazel-crubit/external")

    log(f"Found LLVM project source at: {llvm_proj_dir}")

    # We also need the generated headers.
    bazel_out = "bazel-out"
    fastbuild_dir = None
    for d in os.listdir(bazel_out):
        if d.endswith("-fastbuild") or d.endswith("-opt"):
            fastbuild_dir = os.path.join(bazel_out, d)
            if os.path.exists(os.path.join(fastbuild_dir, "bin", "external")):
                break

    if not fastbuild_dir:
        fastbuild_dir = os.path.join(bazel_out, "k8-fastbuild")

    log(f"Using Bazel output dir: {fastbuild_dir}")

    full_path = os.path.join(fastbuild_dir, "bin", "external", resolved_llvm_dirname)
    gen_llvm_proj_dir = full_path if os.path.isdir(full_path) else None

    if gen_llvm_proj_dir:
        log(f"Found LLVM generated headers at: {gen_llvm_proj_dir}")

    clang_include_paths = [
        os.path.abspath(os.path.join(llvm_proj_dir, "clang", "include")),
        os.path.abspath(os.path.join(llvm_proj_dir, "llvm", "include")),
    ]
    if gen_llvm_proj_dir:
        clang_include_paths.extend([
            os.path.abspath(os.path.join(gen_llvm_proj_dir, "clang", "include")),
            os.path.abspath(os.path.join(gen_llvm_proj_dir, "llvm", "include")),
        ])

    # LLVM Libraries
    bin_external_base = "bazel-bin/external"
    bin_llvm_proj_dir = os.path.join(bin_external_base, resolved_llvm_dirname)

    clang_lib_paths = []
    if os.path.isdir(bin_llvm_proj_dir):
        clang_lib_paths = [
            os.path.abspath(os.path.join(bin_llvm_proj_dir, "clang")),
            os.path.abspath(os.path.join(bin_llvm_proj_dir, "llvm")),
        ]

    # 3. Abseil paths
    absl_src_dir = None
    for d in os.listdir(external_dir):
        if "abseil-cpp" in d:
            full_path = os.path.join(external_dir, d)
            if os.path.isdir(full_path):
                absl_src_dir = full_path
                break
    if not absl_src_dir:
        absl_src_dir = os.path.join(external_dir, "abseil-cpp+")

    log(f"Found Abseil source at: {absl_src_dir}")
    resolved_absl_dirname = os.path.basename(absl_src_dir)

    absl_include_paths = [
        os.path.abspath(absl_src_dir)
    ]

    # Abseil Libraries
    bin_absl_dir = os.path.join(bin_external_base, resolved_absl_dirname)
    if not os.path.isdir(bin_absl_dir):
        bin_absl_dir = os.path.join(bin_external_base, "abseil-cpp+")

    absl_lib_base = os.path.join(bin_absl_dir, "absl")

    # 4. Hermetic Toolchain (if available)
    hermetic_clang = None
    hermetic_clang_xx = None
    hermetic_lib_dir = None
    llvm_ar_path = None

    for d in os.listdir(external_dir):
        if d.startswith("toolchains_llvm"):
            full_path = os.path.join(external_dir, d)
            if os.path.isdir(full_path):
                clang_path = os.path.join(full_path, "bin", "clang")
                clang_xx_path = os.path.join(full_path, "bin", "clang++")
                ar_path = os.path.join(full_path, "bin", "llvm-ar")
                if os.path.exists(clang_path) and os.path.exists(clang_xx_path):
                    hermetic_clang = os.path.abspath(clang_path)
                    hermetic_clang_xx = os.path.abspath(clang_xx_path)
                    if os.path.exists(ar_path):
                        llvm_ar_path = os.path.abspath(ar_path)
                    lib_base = os.path.join(full_path, "lib")
                    linux_lib = os.path.join(lib_base, "x86_64-unknown-linux-gnu")
                    if os.path.isdir(linux_lib):
                        hermetic_lib_dir = os.path.abspath(linux_lib)
                    elif os.path.isdir(lib_base):
                        hermetic_lib_dir = os.path.abspath(lib_base)
                    break

    # 5. Merge libraries into monolithic ones to resolve collisions and cyclic deps
    if not llvm_ar_path:
        fail("llvm-ar not found in toolchains_llvm. Cannot merge libraries.")

    bazel_outputs_dir = os.path.abspath(os.path.join(REPO_ROOT, "cargo", "build", "bazel_outputs"))
    os.makedirs(bazel_outputs_dir, exist_ok=True)

    # Collect and merge Abseil static libraries
    absl_monolithic_path = os.path.join(bazel_outputs_dir, "libabsl_monolithic.a")
    merge_archives(llvm_ar_path, absl_monolithic_path, [absl_lib_base])

    # Collect and merge Clang/LLVM static libraries
    clang_monolithic_path = os.path.join(bazel_outputs_dir, "libclang_monolithic.a")
    merge_archives(llvm_ar_path, clang_monolithic_path, clang_lib_paths)

    # 6. Write results to bazel-env.sh (and to `GITHUB_ENV` if present).
    env_vars = {
        "CLANG_INCLUDE_PATH": ",".join(clang_include_paths),
        "CLANG_LIB_STATIC_PATH": bazel_outputs_dir,
        "ABSL_INCLUDE_PATH": ",".join(absl_include_paths),
        "ABSL_LIB_STATIC_PATH": bazel_outputs_dir,
    }

    if hermetic_clang and hermetic_clang_xx:
        log(f"Found hermetic Clang: {hermetic_clang}")
        env_vars["CC"] = hermetic_clang
        env_vars["CXX"] = hermetic_clang_xx
        env_vars["CXXFLAGS"] = "-stdlib=libc++"

        hermetic_clang_dir = os.path.dirname(hermetic_clang)
        rustflags = [
            f"-C linker={hermetic_clang}",
            f"-C link-arg=-fuse-ld={os.path.join(hermetic_clang_dir, 'ld.lld')}",
            "-C link-arg=-stdlib=libc++",
            "-C link-arg=-lc++abi",
        ]
        if hermetic_lib_dir:
            log(f"Found hermetic Lib dir: {hermetic_lib_dir}")
            rustflags.append(f"-C link-arg=-L{hermetic_lib_dir}")
            rustflags.append(f"-C link-arg=-Wl,-rpath,{hermetic_lib_dir}")

        env_vars["RUSTFLAGS"] = " ".join(rustflags)

    env_sh_path = os.path.join(bazel_outputs_dir, "bazel-env.sh")
    os.makedirs(os.path.dirname(env_sh_path), exist_ok=True)
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

    print("\nTo configure your environment, run:")
    print(f"source {os.path.relpath(env_sh_path, REPO_ROOT)}")

if __name__ == "__main__":
    main()

