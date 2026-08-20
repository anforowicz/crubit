# Workaround for Protobuf rust_proto_library label resolution bug in Bzlmod.
# Protobuf's rust/defs.bzl references the string "//rust:use_upb_kernel" instead
# of Label("@protobuf//rust:use_upb_kernel"). When evaluated in the root
# repository, Bazel resolves this relative label to @//rust:use_upb_kernel.
#
# We define this dummy config_setting (which is always false) so that Bazel
# falls back to the default C++ Protobuf kernel.

config_setting(
    name = "use_upb_kernel",
    values = {"define": "never_true=1"},
    visibility = ["//visibility:public"],
)
