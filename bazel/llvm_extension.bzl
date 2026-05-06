# Part of the Crubit project, under the Apache License v2.0 with LLVM
# Exceptions. See /LICENSE for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

load("@toolchains_llvm//toolchain:rules.bzl", "llvm_toolchain")

def _llvm_source_fetch_impl(repository_ctx):
    commit = "20b6ec66967ac2a8f932863c1abf251e5b17a843"
    url = "https://github.com/llvm/llvm-project/archive/" + commit + ".tar.gz"

    print("Downloading LLVM source from " + url + "...")
    repository_ctx.download_and_extract(
        url = url,
        stripPrefix = "llvm-project-" + commit,
    )

    # Create an empty BUILD file at the root to make it a package,
    # so that files like WORKSPACE can be referenced as labels.
    repository_ctx.file("BUILD.bazel", "")

llvm_source_fetch = repository_rule(
    implementation = _llvm_source_fetch_impl,
)

def _host_zlib_impl(repository_ctx):
    repository_ctx.symlink("/usr/include/zlib.h", "include/zlib.h")
    repository_ctx.file("BUILD.bazel", """
load("@rules_cc//cc:cc_library.bzl", "cc_library")

cc_library(
    name = "zlib-ng",
    includes = ["include"],
    linkopts = ["-lz"],
    visibility = ["//visibility:public"],
)
""")

host_zlib = repository_rule(
    implementation = _host_zlib_impl,
)

def _host_libxml2_impl(repository_ctx):
    repository_ctx.symlink("/usr/include/libxml2", "include")
    repository_ctx.file("BUILD.bazel", """
load("@rules_cc//cc:cc_library.bzl", "cc_library")

cc_library(
    name = "libxml2",
    includes = ["include"],
    linkopts = ["-lxml2"],
    visibility = ["//visibility:public"],
)
""")

host_libxml2 = repository_rule(
    implementation = _host_libxml2_impl,
)

def _host_zstd_impl(repository_ctx):
    repository_ctx.symlink("/usr/include/zstd.h", "include/zstd.h")
    repository_ctx.file("BUILD.bazel", """
load("@rules_cc//cc:cc_library.bzl", "cc_library")

cc_library(
    name = "zstd",
    includes = ["include"],
    linkopts = ["-lzstd"],
    visibility = ["//visibility:public"],
)
""")

host_zstd = repository_rule(
    implementation = _host_zstd_impl,
)

def _llvm_extension_impl(module_ctx):
    # Fetch LLVM source
    llvm_source_fetch(name = "llvm-raw")
    host_zlib(name = "llvm_zlib")
    host_libxml2(name = "llvm_libxml2")
    host_zstd(name = "llvm_zstd")

llvm_extension = module_extension(
    implementation = _llvm_extension_impl,
)
