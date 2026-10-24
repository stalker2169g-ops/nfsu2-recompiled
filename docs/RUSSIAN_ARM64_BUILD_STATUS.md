# Russian ARM64 build status — 2026-10-24

No APK has been produced by this work. Russian rendering has not been verified.

## Changes committed

- Initialize Android command-line tools before invoking sdkmanager.
- Use platform-tools instead of the removed SDK tools package.
- Fetch pinned pcrecomp 35548b8 and apply the repository's patches.
- Fetch pinned DXVK native c8dc91fabd00cac11d697ccf07426e798393cd40, prepare the Android source and generate shaders.
- Build explicitly for arm64-v8a.
- Replace transient CI codepage rewriting with committed runtime support for explicit CP1251 and Russian ACP / thread ACP, retaining CP1252 for other languages.
- Implement GetACP and GetThreadLocale selection for Russian; accept CP1251 in GetCPInfo and Russian LCID in LCMapStringW.
- Offer Russian in the launcher when LANGUAGES/Russian.bin exists, and accept the selection in the native runtime.
- Add scripts/check_cp1251.py to compare the production byte codec with Python's CP1251 reference.

## Evidence

1. Original run 40086885267 failed with sdkmanager: command not found.
2. Run 40087092286 exposed setup-android's attempt to install removed package tools.
3. Run 40087121355 installed SDK/NDK successfully, then failed because DXVK source had not been prepared.
4. Run [40087215620](https://github.com/stalker2169g-ops/nfsu2-recompiled/actions/runs/40087215620), commit f06ae26242c7ee6cb58f3d1db8bff90e874c4b9d:
   - SDK installation succeeded.
   - CP1251 check passed (all 256 byte mappings and reverse mappings, ACP selection, unrepresentable character and CP1252 regressions). Also passed locally with C++17, Wall/Wextra/Werror.
   - pcrecomp patch application and DXVK preparation succeeded.
   - 54 built-in shaders generated and validated for Vulkan 1.1.
   - ARM64 CMake configuration failed at android/app/src/main/cpp/CMakeLists.txt:22: Generate the local game C first; see the project README.
   - Artifact API returned zero artifacts.

## Required input to continue

This repository deliberately excludes SPEED2.EXE and src/recomp/gen. No game executable or generated game sources were supplied in the workspace. The build needs generated code from the owner's executable, not dummy functions or an unrelated prebuilt APK. The workflow still needs the game input and a generation step once that input is available.

Supply an archive from the owner's game installation containing SPEED2.EXE, preferably the installation including LANGUAGES, FRONTEND and GLOBAL for Russian text/font investigation. The documented default executable is 4,800,512 bytes, SHA-256 f9dd86c054878ce6276beb07c1fd61874f7a1e4bf1f241b084c65b73e24168a7. A different executable requires build compatibility checks.

## Limits of validation

The native application has not compiled or linked yet. Byte-codec tests do not execute the complete guest Win32 conversion APIs. Launcher language selection and the game's interpretation of Russian have not been exercised on a device. Russian assets and glyph coverage have not been inspected; no font changes were made. Installation, startup and in-game Cyrillic rendering remain unverified.
