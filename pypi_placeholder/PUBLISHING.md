# Publishing the SureshotSDK name placeholder

Build: `python3 -m build pypi_placeholder` (outputs to `pypi_placeholder/dist/`).
Upload: `python3 -m twine upload pypi_placeholder/dist/*`.
Afterwards, swap the account-wide PyPI token for a project-scoped one.
