# Deploys the text-translate Worker and binds it to its custom domain.
# Needs CF_API_TOKEN (user env var) with Workers Scripts: Edit.
# The shared secret lives in ..\.env as TEXT_PROXY_KEY (created here if missing,
# never printed); it is uploaded as the Worker secret PROXY_KEY.

$ErrorActionPreference = 'Stop'
$script   = 'text-translate'
$hostname = 'text-tr.joelgoncalves.es'
$envFile  = Join-Path $PSScriptRoot '..\.env'

$tok = "$((Get-ItemProperty HKCU:\Environment -Name CF_API_TOKEN).CF_API_TOKEN)".Trim()
$h = @{ Authorization = "Bearer $tok" }
$api = 'https://api.cloudflare.com/client/v4'

if (-not (Test-Path $envFile)) { New-Item -ItemType File $envFile | Out-Null }
$lines = @(Get-Content $envFile)
$key = ($lines | Where-Object { $_ -like 'TEXT_PROXY_KEY=*' } | Select-Object -First 1) -replace '^TEXT_PROXY_KEY=', ''
if (-not $key) {
    $key = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLower()
    Add-Content $envFile "TEXT_PROXY_KEY=$key"
}
if (-not ($lines | Where-Object { $_ -like 'TEXT_PROXY_URL=*' })) {
    Add-Content $envFile "TEXT_PROXY_URL=https://$hostname/"
}

$zone = (Invoke-RestMethod "$api/zones?name=joelgoncalves.es" -Headers $h).result[0]
$acc = $zone.account.id

# Upload the module + secret binding (multipart).
$metadata = @{
    main_module        = 'worker.js'
    compatibility_date = '2026-09-01'
    bindings           = @(@{ type = 'secret_text'; name = 'PROXY_KEY'; text = $key })
} | ConvertTo-Json -Depth 5
$form = [System.Net.Http.MultipartFormDataContent]::new()
$meta = [System.Net.Http.StringContent]::new($metadata, [Text.Encoding]::UTF8, 'application/json')
$form.Add($meta, 'metadata')
$js = [System.Net.Http.ByteArrayContent]::new([IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'worker.js')))
$js.Headers.ContentType = 'application/javascript+module'
$form.Add($js, 'worker.js', 'worker.js')
$client = [System.Net.Http.HttpClient]::new()
$client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $tok)
$resp = $client.PutAsync("$api/accounts/$acc/workers/scripts/$script", $form).Result
$body = $resp.Content.ReadAsStringAsync().Result
if (-not $resp.IsSuccessStatusCode) { throw "Upload failed ($([int]$resp.StatusCode)): $body" }
Write-Host "Worker '$script' uploaded."

# Custom domain (creates its own DNS record, overriding the tunnel wildcard).
$domain = @{ environment = 'production'; hostname = $hostname; service = $script; zone_id = $zone.id } | ConvertTo-Json
Invoke-RestMethod "$api/accounts/$acc/workers/domains" -Method Put -Headers $h -ContentType 'application/json' -Body $domain | Out-Null
Write-Host "Bound to https://$hostname/"
