Windows validation and shared reliability fixes:

- Fix Windows Ctrl/Alt/Windows-key shortcuts on non-English keyboard layouts.
- Make Windows updates recover the executable and runtime together on failure.
- Update connected viewers immediately when Allow control is changed.
- Reject incomplete internet file uploads and stop transfers when control is revoked.
- Handle additional Windows reserved filenames; add native Windows notifications.
- Run shared regression tests on Windows, Apple silicon and Intel Mac; require captured video in Windows build checks.

Windows and macOS use the same host, viewer and protocol code. Windows still requires a virtual display driver or HDMI dummy plug to create an additional host display; Mac hosts can create a virtual display directly. See the [validation checklist](https://github.com/Nikita-Shulga/Hop/blob/main/docs/VALIDATION.md) for automated coverage and checks that require physical devices or separate networks.
