"""KubeSentra MCP tool servers (k8s-read, prometheus, loki, knowledge).

Write-capable server (k8s-write) is added in Phase 7 with its own
ServiceAccount and is loaded only by the executor after human approval.
"""
