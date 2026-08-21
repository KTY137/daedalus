# Launcher: startet den Serena-Watchdog mit SAUBERER Umgebung.
#
# Grund: Wird der Watchdog aus einer laufenden Claude-Code-Session heraus
# gestartet, erben die Kind-Sessions deren Prozess-Variablen (CLAUDECODE,
# CLAUDE_CODE_CHILD_SESSION, CLAUDE_CODE_SESSION_ID, ...). Eine so markierte
# claude.exe verhaelt sich wie eine verschachtelte Session und scheitert mit
# "API Error: Connection refused" (MEASURED 2026-08-17: Attempts 1-9, 0 Arbeit).
# Dieser Launcher entfernt die Marker im eigenen Prozess, bevor er die
# eigentliche Watchdog-ps1 startet. Env-Aenderungen bleiben prozesslokal.

[CmdletBinding()]
param(
    [string]$ProjectPath = "C:\Users\nukei\Desktop\agent_env.worktrees\watchdog-mission",
    [string]$PromptFile  = "C:\Users\nukei\Desktop\agent_env.worktrees\watchdog-mission\claude-mission-gate-arc.md",
    [int]$MaxHours = 48,
    [switch]$NewMission
)

$ErrorActionPreference = "Stop"

Get-ChildItem Env: |
    Where-Object {
        $_.Name -like "CLAUDE*" -or
        $_.Name -eq "CLAUDECODE" -or
        $_.Name -eq "AI_AGENT" -or
        $_.Name -like "MCP_CLAUDE*"
    } |
    ForEach-Object { Remove-Item "Env:$($_.Name)" -ErrorAction SilentlyContinue }

$watchdog = Join-Path $PSScriptRoot "claude-serena-watchdog.ps1"
$arguments = @{
    ProjectPath = $ProjectPath
    PromptFile  = $PromptFile
    MaxHours    = $MaxHours
}
if ($NewMission) { $arguments.NewMission = $true }

& $watchdog @arguments
