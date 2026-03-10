# ---------------- Пути ----------------

$anythingPath = "C:\Users\user\AppData\Local\Programs\AnythingLLM\AnythingLLM.exe"

$projectDir = "C:\Users\user\OneDrive\Рабочий стол\Ферма\farm_guardian"
$venvPython = "$projectDir\venv\Scripts\python.exe"
$botFile    = "$projectDir\bot.py"


# ---------------- Запуск AnythingLLM ----------------

if (Test-Path $anythingPath) {
    Start-Process $anythingPath
} else {
    Write-Host "AnythingLLM.exe не найден по пути:"
    Write-Host $anythingPath
}

# Даём AnythingLLM поднять API
Start-Sleep -Seconds 10


# ---------------- Запуск бота ----------------

if (Test-Path $venvPython) {
    Start-Process `
        -WorkingDirectory $projectDir `
        -FilePath $venvPython `
        -ArgumentList $botFile
} else {
    Write-Host "python из venv не найден:"
    Write-Host $venvPython
}
