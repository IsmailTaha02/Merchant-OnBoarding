param(
  [string]$StackName = "gweb-merchant-onboarding",
  [string]$Region = "eu-west-2",
  [string]$FrontendOrigin = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"
$response = aws cloudformation describe-stacks --stack-name $StackName --region $Region --output json
if ($LASTEXITCODE -ne 0) { throw "Could not read CloudFormation outputs. Confirm the stack deployed and AWS CLI is signed in." }
$stack = $response | ConvertFrom-Json
$outputs = @{}
foreach ($output in $stack.Stacks[0].Outputs) { $outputs[$output.OutputKey] = $output.OutputValue }
foreach ($required in @("ApiUrl", "AuthDomain", "UserPoolClientId")) {
  if (-not $outputs.ContainsKey($required)) { throw "Stack output '$required' was not found." }
}

$config = @{
  apiBaseUrl = $outputs.ApiUrl
  demoMode = $false
  authDomain = $outputs.AuthDomain
  userPoolClientId = $outputs.UserPoolClientId
  redirectUri = "$($FrontendOrigin.TrimEnd('/'))/"
} | ConvertTo-Json -Compress
$configPath = Join-Path $PSScriptRoot "..\frontend\config.js"
$content = "// Generated from the deployed CloudFormation outputs. Do not commit production endpoint values.`nwindow.MERCHANT_APP_CONFIG = $config;`n"
[System.IO.File]::WriteAllText((Resolve-Path $configPath), $content, [System.Text.UTF8Encoding]::new($false))
Write-Output "Frontend configured for $($outputs.ApiUrl) and $($FrontendOrigin)."
