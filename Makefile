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
SRC      := src/main.cpp src/config.cpp src/footprint.cpp
RC       := src/app.rc
ICONS    := src/ExplorerF11.ico src/ExplorerF11-paused.ico
DEP      := $(wildcard src/*.h)

CXXFLAGS ?= -std=c++17 -Os -Wall -Wextra
CXXFLAGS += -municode
LDFLAGS  += -mwindows -static -static-libgcc -static-libstdc++ -s
LDLIBS   := -luser32 -lshell32 -ladvapi32

.PHONY: all debug test clean

all: $(OUT)

$(OUT): $(SRC) $(RC) $(ICONS) $(DEP)
	@mkdir -p dist
	$(CXX) $(CXXFLAGS) $(SRC) $(RC) -o $@ $(LDFLAGS) $(LDLIBS)
	@echo "built $@"

debug: CXXFLAGS := -std=c++17 -O0 -g -Wall -Wextra -municode -D_DEBUG
debug: LDFLAGS  := -municode -static -static-libgcc -static-libstdc++
debug: clean $(OUT)

test: $(OUT)
	python tests/test_menu_order.py
	python tests/test_footprint_report.py
	python tests/test_registry_policy.py
	python tests/test_language.py
	python tests/test_icons.py
	python tests/test_tray_cleanup.py
	python tests/test_smoke.py

clean:
	rm -rf dist
