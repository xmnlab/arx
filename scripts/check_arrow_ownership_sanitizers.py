#!/usr/bin/env python3
"""
title: Exercise Arrow ownership paths under native sanitizers.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from irx.builder.runtime.arrow.feature import (
    ARROW_RUNTIME_CAPABILITIES,
    arrow_native_source_dir,
    build_arrow_native_artifact,
)
from irx.builder.runtime.arrowcpp import arrowcpp_linker_flags
from irx.builder.runtime.features import NativeArtifact
from irx.builder.runtime.linking import compile_native_artifacts

SANITIZER_FLAGS = (
    "-fsanitize=address,undefined,leak",
    "-fno-omit-frame-pointer",
    "-O1",
)
SANITIZER_CAPABILITIES = ("core", "array", "tensor", "dataframe")
HARNESS_SOURCE = r"""
#include "irx_arrow_abi_generated.h"

#include <arrow/memory_pool.h>

#include <cstdint>
#include <cstdio>

#define IRX_REQUIRE_OK(expression)                                      \
  do {                                                                  \
    const irx_arrow_status status = (expression);                        \
    if (status != IRX_ARROW_STATUS_OK) {                                 \
      std::fprintf(stderr, "%s failed with status %d: %s\n",           \
                   #expression, status, irx_arrow_last_error());         \
      return false;                                                      \
    }                                                                   \
  } while (false)

static bool exercise_array_and_table(int64_t iteration) {
  irx_arrow_error_handle* error = nullptr;
  irx_arrow_array_builder_handle* builder = nullptr;
  IRX_REQUIRE_OK(irx_arrow_array_builder_new(
      IRX_ARROW_TYPE_INT64, &builder, &error));
  IRX_REQUIRE_OK(irx_arrow_array_builder_append_int(
      builder, iteration, &error));
  IRX_REQUIRE_OK(irx_arrow_array_builder_append_null(
      builder, 1, &error));

  irx_arrow_array_handle* array = nullptr;
  IRX_REQUIRE_OK(irx_arrow_array_builder_finish(
      &builder, &array, &error));
  if (builder != nullptr) {
    std::fprintf(stderr, "array builder was not consumed\n");
    return false;
  }

  const char* names[] = {"value"};
  irx_arrow_array_handle* arrays[] = {array};
  irx_arrow_table_handle* table = nullptr;
  IRX_REQUIRE_OK(irx_arrow_table_new_from_arrays(
      1, names, arrays, &table, &error));

  irx_arrow_chunked_array_handle* column = nullptr;
  IRX_REQUIRE_OK(irx_arrow_table_column_by_index(
      table, 0, &column, &error));
  if ((iteration % 2) == 0) {
    IRX_REQUIRE_OK(irx_arrow_table_release(&table, &error));
    IRX_REQUIRE_OK(irx_arrow_chunked_array_release(&column, &error));
  } else {
    IRX_REQUIRE_OK(irx_arrow_chunked_array_release(&column, &error));
    IRX_REQUIRE_OK(irx_arrow_table_release(&table, &error));
  }
  IRX_REQUIRE_OK(irx_arrow_array_release(&array, &error));
  if (table != nullptr || column != nullptr || array != nullptr) {
    std::fprintf(stderr, "released Arrow output remained non-null\n");
    return false;
  }
  return true;
}

static bool exercise_tensor(int64_t iteration) {
  irx_arrow_error_handle* error = nullptr;
  const int64_t shape[] = {2};
  irx_arrow_tensor_builder_handle* builder = nullptr;
  IRX_REQUIRE_OK(irx_arrow_tensor_builder_new(
      IRX_ARROW_TYPE_INT64, 1, shape, nullptr, &builder, &error));
  IRX_REQUIRE_OK(irx_arrow_tensor_builder_append_int(
      builder, iteration, &error));
  IRX_REQUIRE_OK(irx_arrow_tensor_builder_append_int(
      builder, iteration + 1, &error));

  irx_arrow_tensor_handle* tensor = nullptr;
  IRX_REQUIRE_OK(irx_arrow_tensor_builder_finish(
      &builder, &tensor, &error));
  IRX_REQUIRE_OK(irx_arrow_tensor_release(&tensor, &error));
  if (builder != nullptr || tensor != nullptr) {
    std::fprintf(stderr, "released tensor output remained non-null\n");
    return false;
  }
  return true;
}

static void release_schema_source(ArrowSchema* schema) {
  schema->release = nullptr;
}

static bool exercise_schema() {
  ArrowSchema item{};
  item.format = "u";
  item.name = "item";
  item.flags = 2;
  item.release = release_schema_source;
  ArrowSchema* children[] = {&item};
  ArrowSchema source{};
  source.format = "+l";
  source.name = "values";
  source.n_children = 1;
  source.children = children;
  source.release = release_schema_source;
  irx_arrow_error_handle* error = nullptr;
  irx_arrow_schema_handle* owner = nullptr;
  IRX_REQUIRE_OK(irx_arrow_schema_import_copy(&source, &owner, &error));
  if (source.release != release_schema_source ||
      item.release != release_schema_source) {
    std::fprintf(stderr, "schema copy consumed producer callbacks\n");
    return false;
  }
  source.release(&source);
  item.release(&item);
  ArrowSchema exported{};
  IRX_REQUIRE_OK(irx_arrow_schema_export(owner, &exported, &error));
  IRX_REQUIRE_OK(irx_arrow_schema_release(&owner, &error));
  if (exported.release == nullptr || exported.n_children != 1) {
    return false;
  }
  exported.release(&exported);
  return owner == nullptr && exported.release == nullptr;
}

int main() {
  constexpr int64_t kIterations = 256;
  arrow::MemoryPool* pool = arrow::default_memory_pool();
  const int64_t baseline = pool->bytes_allocated();
  for (int64_t iteration = 0; iteration < kIterations; ++iteration) {
    if (!exercise_array_and_table(iteration) ||
        !exercise_tensor(iteration) || !exercise_schema()) {
      return 1;
    }
    if (pool->bytes_allocated() != baseline) {
      std::fprintf(stderr, "live Arrow pool bytes grew after iteration %lld\n",
                   static_cast<long long>(iteration));
      return 2;
    }
  }
  return 0;
}
""".lstrip()


def sanitizer_artifact(capability: str) -> NativeArtifact:
    """
    title: Build one sanitizer-instrumented Arrow runtime artifact.
    parameters:
      capability:
        type: str
    returns:
      type: NativeArtifact
    """
    if capability not in ARROW_RUNTIME_CAPABILITIES:
        raise ValueError(f"Unknown Arrow runtime capability '{capability}'")
    artifact = build_arrow_native_artifact(capability)
    return replace(
        artifact,
        compile_flags=(*artifact.compile_flags, *SANITIZER_FLAGS),
    )


def write_harness(build_dir: Path) -> NativeArtifact:
    """
    title: Write and describe the sanitizer ownership harness.
    parameters:
      build_dir:
        type: Path
    returns:
      type: NativeArtifact
    """
    source = build_dir / "arrow_ownership_sanitizer_harness.cc"
    source.write_text(HARNESS_SOURCE, encoding="utf8")
    native_root = arrow_native_source_dir()
    buffer_native_root = native_root.parent.parent / "buffer" / "native"
    return NativeArtifact(
        kind="cxx_source",
        path=source,
        include_dirs=(
            native_root,
            buffer_native_root.resolve(),
            *build_arrow_native_artifact("core").include_dirs,
        ),
        compile_flags=("-std=c++20", *SANITIZER_FLAGS),
    )


def build_harness(build_dir: Path, cxx_binary: str) -> Path:
    """
    title: Compile and link the Arrow ownership sanitizer harness.
    parameters:
      build_dir:
        type: Path
      cxx_binary:
        type: str
    returns:
      type: Path
    """
    artifacts = (
        *(
            sanitizer_artifact(capability)
            for capability in SANITIZER_CAPABILITIES
        ),
        write_harness(build_dir),
    )
    link_inputs = compile_native_artifacts(
        artifacts,
        build_dir,
        cxx_binary=cxx_binary,
    )
    executable = build_dir / "arrow_ownership_sanitizer_harness"
    command = [cxx_binary, *SANITIZER_FLAGS]
    command.extend(str(path) for path in link_inputs.objects)
    command.extend(link_inputs.linker_flags)
    command.extend(arrowcpp_linker_flags())
    command.extend(("-o", str(executable)))
    subprocess.run(command, check=True)
    return executable


def run_harness(executable: Path, *, detect_leaks: bool = True) -> None:
    """
    title: Run the ownership harness with fail-fast sanitizer settings.
    parameters:
      executable:
        type: Path
      detect_leaks:
        type: bool
    """
    environment = os.environ.copy()
    environment["ASAN_OPTIONS"] = (
        f"detect_leaks={int(detect_leaks)}:halt_on_error=1"
    )
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    if detect_leaks:
        environment["LSAN_OPTIONS"] = "exitcode=23"
    subprocess.run([str(executable)], check=True, env=environment)


def main(argv: Sequence[str] | None = None) -> int:
    """
    title: Build and execute the Arrow ownership sanitizer harness.
    parameters:
      argv:
        type: Sequence[str] | None
    returns:
      type: int
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cxx",
        default=os.environ.get("CXX", "c++"),
        help="C++ compiler with ASan, UBSan, and LSan support",
    )
    parser.add_argument(
        "--skip-leak-detection",
        action="store_true",
        help="disable LSan only when the execution environment uses ptrace",
    )
    arguments = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(
        prefix="irx-arrow-ownership-sanitizers-"
    ) as temporary_directory:
        build_dir = Path(temporary_directory)
        executable = build_harness(build_dir, arguments.cxx)
        run_harness(
            executable,
            detect_leaks=not arguments.skip_leak_detection,
        )

    print("Arrow ownership sanitizer harness passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
