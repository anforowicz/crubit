#!/usr/bin/env python3
# Part of the Crubit project, under the Apache License v2.0 with LLVM
# Exceptions. See /LICENSE for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

import argparse
import os
import re
import sys
import urllib.request


def get_latest_nightly_date():
    url = "https://static.rust-lang.org/dist/channel-rust-nightly.toml"
    try:
        with urllib.request.urlopen(url) as response:
            content = response.read().decode()
            match = re.search(r'^date = "([^"]+)"', content, re.MULTILINE)
            if match:
                return match.group(1)
            else:
                print("Failed to find date in TOML")
                sys.exit(1)
    except Exception as e:
        print(f"Failed to fetch: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Update Rust nightly in MODULE.bazel")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check and report versions without making changes",
    )
    args = parser.parse_args()

    latest_date = get_latest_nightly_date()
    print(f"Latest available nightly date: {latest_date}")

    if args.dry_run:
        print("Dry run: not making any changes.")
        sys.exit(0)

    with open("MODULE.bazel", "r") as f:
        content = f.read()

    # Unconditionally update MODULE.bazel
    new_content = re.sub(
        r'versions = \["nightly/[^"]+"\]',
        f'versions = ["nightly/{latest_date}"]',
        content,
    )

    with open("MODULE.bazel", "w") as f:
        f.write(new_content)

    print("Successfully updated MODULE.bazel")

    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"latest_date={latest_date}\n")


if __name__ == "__main__":
    main()
