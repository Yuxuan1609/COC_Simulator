# watchdog.ps1 — 心跳监控 + 防待机
# 用法: .\watchdog.ps1 -LogDir "logs\llm_player\<timestamp>" [-TimeoutMin 5] [-InitDelay 5]
param([string]$LogDir, [int]$TimeoutMin=5, [int]$InitDelay=5)

# ── 防系统待机 ──
Add-Type -Name System -Namespace Win32 -MemberDefinition @'
[DllImport("kernel32.dll")]
public static extern uint SetThreadExecutionState(uint esFlags);
'@
[Win32.System]::SetThreadExecutionState(0x80000003)  # ES_CONTINUOUS | SYSTEM_REQUIRED | DISPLAY_REQUIRED
Write-Host "[INFO] 已防止系统待机"

# ── 初始等待：让 llm_player 先跑 InitDelay 分钟建立日志 ──
Write-Host "[INFO] 等待 ${InitDelay}min 开始心跳检测..."
Start-Sleep -Seconds ($InitDelay * 60)

$lastCount = 0
$stuckRounds = 0
while ($true) {
    Start-Sleep -Seconds ($TimeoutMin * 60)
    $currentCount = @(Get-ChildItem -LiteralPath $LogDir -Recurse -File -ErrorAction SilentlyContinue).Count
    if ($currentCount -eq $lastCount -and $currentCount -gt 0) {
        $stuckRounds++
        Write-Host "[WARN] 日志目录 $LogDir 无新文件 ($stuckRounds 轮)"
        if ($stuckRounds -ge 1) {
            Write-Host "[FATAL] 连续 ${TimeoutMin}min 无输出，疑似死锁，杀 Python 进程..."
            Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
            break
        }
    } else {
        $stuckRounds = 0
    }
    $lastCount = $currentCount
}

# ── 恢复待机 ──
[Win32.System]::SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS
Write-Host "[INFO] 已恢复待机策略"
