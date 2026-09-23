# Third-party notices

TitleVision Assistant uses separately licensed components. The project's rights-reserved notice does not override dependency licenses.

| Component | Purpose | Upstream |
| --- | --- | --- |
| Python / Tcl / Tk | Runtime and desktop UI | https://www.python.org/ and https://www.tcl-lang.org/ |
| Playwright | Browser automation | https://github.com/microsoft/playwright-python |
| tzdata | IANA timezone data | https://github.com/python/tzdata |
| greenlet / pyee / typing_extensions | Playwright dependencies | Their installed distribution metadata |
| PyInstaller and hooks | Executable build system | https://pyinstaller.org/ |
| Inno Setup | Installer compiler | https://jrsoftware.org/ |

The build copies available installed dependency license files into `third-party-licenses/` in the bundle. Consult those files and upstream licenses for exact terms. The dependency inventory includes build dependencies as well as runtime dependencies; it is not an SPDX/CycloneDX SBOM.

Microsoft Edge and Google Chrome are installed separately; neither browser is redistributed in this release.
