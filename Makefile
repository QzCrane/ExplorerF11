# ExplorerF11 - GNU make build (MinGW-w64 / MSYS2).
#
#   make            release build -> dist/ExplorerF11.exe
#   make debug      symbols, console subsystem
#   make test       run the python test suite against the built exe
#   make release    build, gate, tag, publish and verify in one command
#   make clean
#
# The MSVC equivalent is build.bat; both produce the same single exe.

CXX      ?= g++
WINDRES  ?= windres
OUT      := dist/ExplorerF11.exe
OBJDIR   := dist/obj
SRC      := src/main.cpp src/config.cpp src/residue.cpp src/i18n_extra.cpp
OBJ      := $(patsubst src/%.cpp,$(OBJDIR)/%.o,$(SRC))
RC       := src/app.rc
RES      := $(OBJDIR)/app.res
ICONS    := src/ExplorerF11.ico src/ExplorerF11-paused.ico
DEP      := $(wildcard src/*.h)

# Each translation unit is compiled on its own so the four can run at once.
# A single g++ invocation compiling and linking in one step is serial and
# uncacheable; split this way the bytes are identical (verified against the
# released hash) and the four compiles overlap. -j applies only to the object
# files: every other target has a one-line recipe, so nothing else in this file
# becomes concurrent.
MAKEFLAGS += -j

CXXFLAGS ?= -std=c++23 -Os -Wall -Wextra
CXXFLAGS += -municode
LDFLAGS  += -municode -mwindows -static -static-libgcc -static-libstdc++ -s
LDLIBS   := -luser32 -lshell32 -ladvapi32

.PHONY: all debug test i18n clean

all: $(OUT)

$(OBJDIR):
	@mkdir -p $(OBJDIR)

$(OBJDIR)/%.o: src/%.cpp $(DEP) | $(OBJDIR)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(RES): $(RC) $(ICONS) $(DEP) | $(OBJDIR)
	$(WINDRES) -I src $(RC) -O coff -o $@

$(OUT): $(OBJ) $(RES)
	$(CXX) $(OBJ) $(RES) -o $@ $(LDFLAGS) $(LDLIBS)
	@echo "built $@"

debug: CXXFLAGS := -std=c++23 -O0 -g -Wall -Wextra -municode -D_DEBUG
debug: LDFLAGS  := -municode -static -static-libgcc -static-libstdc++
debug: clean $(OUT)

.PHONY: refresh-facts bench check-remote release

# One command from clean checkout to verified release. Every stage is
# idempotent and resumable: `make release ARGS=--from tag` re-enters after an
# interruption, `ARGS=--dry-run` stops before anything becomes public.
# See docs/RELEASING.md for the specification this implements.
release:
	python tools/release.py $(ARGS)

# The repository's prose is gated locally, but four surfaces exist only on
# GitHub: the tag's tree (what "Browse files" and the source archive show), the
# release body, the uploaded assets, and the repository description. Each has
# drifted at least once and each time a person found it. This checks them
# against release_facts.py. Needs an authenticated `gh`; not part of `test`.
check-remote:
	python tools/check_github_sync.py

# Diagnostic micro-benchmark of the behaviour hot paths. NOT a gate: it is a
# reproducible measuring stick, not a pass/fail check. Run on demand to back a
# performance claim with a number. See tools/bench_hotpaths.cpp.
BENCH := dist/bench_hotpaths.exe
BENCH_SRC := tools/bench_hotpaths.cpp src/residue.cpp src/config.cpp src/i18n_extra.cpp
bench:
	$(CXX) $(filter-out -municode,$(CXXFLAGS)) -I. $(BENCH_SRC) -o $(BENCH) -static -static-libgcc -static-libstdc++ -luser32 -lshell32 -ladvapi32
	@echo "built $(BENCH) - run it with an iteration count, e.g. dist\\bench_hotpaths.exe 400"

test: $(OUT)
	python tools/check_i18n.py
	python tools/audit_i18n.py
	python tools/check_help_align.py
	python tools/check_release_facts.py
	python tools/check_gate_inventory.py
	python tests/test_lang_names.py
	python tests/test_menu_order.py
	python tests/test_residue_report.py
	python tests/test_registry_policy.py
	python tests/test_language.py
	python tests/test_icons.py
	python tests/test_tray_cleanup.py
	python tests/test_smoke.py
	python tests/test_robustness.py

# Regenerate the translation table after adding or editing a T() call.
# tools/sync_i18n.py reports any key that still needs a translation.
i18n:
	python tools/sync_i18n.py

# Re-derive release_facts.py and measurement.json from src/app.h, the test
# recipe, the built exe and a full test run. Run this after changing a gate or
# rebuilding; never edit the facts by hand.
refresh-facts:
	python tools/refresh_facts.py

clean:
	rm -rf dist
