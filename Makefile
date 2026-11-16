# ExplorerF11 - GNU make build (MinGW-w64 / MSYS2).
#
#   make            release build -> dist/ExplorerF11.exe
#   make debug      symbols, console subsystem
#   make test       run the python test suite against the built exe
#   make clean
#
# The MSVC equivalent is build.bat; both produce the same single exe.

CXX      ?= g++
WINDRES  ?=
OUT      := dist/ExplorerF11.exe
SRC      := src/main.cpp src/config.cpp src/residue.cpp src/i18n_extra.cpp
RC       := src/app.rc
ICONS    := src/ExplorerF11.ico src/ExplorerF11-paused.ico
DEP      := $(wildcard src/*.h)

CXXFLAGS ?= -std=c++23 -Os -Wall -Wextra
CXXFLAGS += -municode
LDFLAGS  += -mwindows -static -static-libgcc -static-libstdc++ -s
LDLIBS   := -luser32 -lshell32 -ladvapi32

.PHONY: all debug test i18n clean

all: $(OUT)

$(OUT): $(SRC) $(RC) $(ICONS) $(DEP)
	@mkdir -p dist
	$(CXX) $(CXXFLAGS) $(SRC) $(RC) -o $@ $(LDFLAGS) $(LDLIBS)
	@echo "built $@"

debug: CXXFLAGS := -std=c++23 -O0 -g -Wall -Wextra -municode -D_DEBUG
debug: LDFLAGS  := -municode -static -static-libgcc -static-libstdc++
debug: clean $(OUT)

.PHONY: refresh-facts

test: $(OUT)
	python tools/check_i18n.py
	python tools/audit_i18n.py
	python tools/check_help_align.py
	python tools/check_release_facts.py
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
