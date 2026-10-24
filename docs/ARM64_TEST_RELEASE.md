ARM64 launcher test built from commit 182221982e2591124b68680d9c59888482a583e6 in Actions run 40142832311.

The Java launcher is compiled from this repository. Native libraries are reused byte-for-byte from the official codepdbh/nfsu2-recompiled v0.14.10 ARM64 APK (upstream APK SHA256 9c6c80b364bbe1399355b22a06fa9f4c16f425229cae00ebee425843cb9cf282). This build requires no EXE as a build input.

The CP1251 changes committed in this repository are NOT compiled into this prebuilt native runtime. In-game Russian language selection and Cyrillic rendering are NOT verified. This is a launcher/packaging test APK, not a confirmed Russian fix.

Verified: Gradle build succeeded; packaged libraries are ARM64 and identical to the pinned upstream libraries; APK Signature Scheme v2 verification passed. No Android device startup/gameplay test was performed.

APK SHA256: 94cdbdcb6ce083b2711267019d47e726ad8a49b853dea317754cf5a39e3d3ed9
