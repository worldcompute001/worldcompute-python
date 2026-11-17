# Publishing World Compute

Use PyPI trusted publishing; do not store a permanent PyPI token in GitHub.
The author and maintainer are World Compute (team@worldcompute.org).

## One-time owner setup

Sign into the intended World Compute PyPI owner account, verify email, and enable
PyPI-required two-factor authentication. For the first release, add a pending
publisher at https://pypi.org/manage/account/publishing/ with:

| Field | Value |
|---|---|
| PyPI project | `worldcompute` |
| GitHub owner | `worldcompute001` |
| Repository | `worldcompute-python` |
| Workflow filename | `publish.yml` |
| Environment | `pypi` |

Create the GitHub repository environment `pypi` before publishing. The first
successful upload creates the project under the account that registered the
pending publisher. A name lookup returning 404 does not reserve the name.
Reference: https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/

## Release

1. Merge the release PR with green CI. Check `pyproject.toml` version.
2. Publish a GitHub prerelease tagged `v0.1.0a1` from that exact merged commit.
3. The `publish.yml` workflow tests, builds and checks the distributions, installs
   the wheel into a clean environment, then publishes using short-lived identity.
4. Verify `python -m pip install worldcompute==0.1.0a1` in a new environment.
5. Run `worldcompute-quickstart` against simulation with a fresh browser login.
   Physical testing is separate and requires attended clearance.
6. Update README and website publication status only after upload succeeds.

Do not reuse a published version. For a defective release, yank it on PyPI and
publish a corrected version. No hardware or service rollout is involved.

## Qualification evidence

- Remote simulation: request `339982bb-c4f2-4fdb-af50-2046d1687c75`, completed,
  measured targets, session stopped/released.
- Attended SO100 reset: request `5bc65e51-2170-4105-871e-ed54726bc64a`, completed,
  all six joints within 0.5 degrees, session stopped/released.
- These runs used the source SDK. Release wheel installation and public-index
  installation are separate checks; neither implies all physical modes are tested.
