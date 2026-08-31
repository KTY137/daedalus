# Pinned OpenVSCode image

The image includes the same `vscode-agent-env` adapter used in a normal VS Code
installation. Build it from the repository root after producing the VSIX:

```powershell
Push-Location vscode-agent-env
npm.cmd ci
npm.cmd run build:vsix
Pop-Location
docker build --pull=false --file packaging/openvscode/Dockerfile --tag daedalus/openvscode-server:1.109.5 .
```

`Dockerfile` copies `vscode-agent-env/dist/daedalus-vscode.vsix` and installs it
with OpenVSCode's local `--install-extension` command. It does not contact an
extension marketplace at image runtime. The base image and OpenVSCode release
remain pinned in the Dockerfile; this document makes no claim that Docker
itself or the already pinned build-time source archive is offline.

The extension is an adapter only. Its editor-context request is fixed to the
local Daedalus API; project identity, policy, provider admission, effects,
evidence, and promotion remain owned by the Daedalus kernel.
