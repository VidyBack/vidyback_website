$files = @(
    "index.html",
    "about.html",
    "blog.html",
    "blog-post-1.html",
    "blog-post-2.html",
    "blog-post-3.html",
    "contact.html",
    "disclaimer.html",
    "faq.html",
    "features.html",
    "integrations.html",
    "platforms.html",
    "pricing.html",
    "privacypolicy.html",
    "shopify.html",
    "squarespace.html",
    "terms.html",
    "wix.html",
    "ecwid.html",
    "etsy.html",
    "jumpseller.html",
    "competitors.html"
)

$oldText = '                        <li><a href="terms.html">Terms of Service</a></li>'
$newText = '                        <li><a href="terms.html">Terms of Service</a></li>
                        <li><a href="cookies-policy.html">Cookies Policy</a></li>'

foreach ($file in $files) {
    $filePath = Join-Path "." $file
    if (Test-Path $filePath) {
        $content = Get-Content $filePath -Raw
        if ($content -contains $oldText) {
            $newContent = $content -replace [regex]::Escape($oldText), $newText
            Set-Content $filePath $newContent -Encoding UTF8 -NoNewline
            Write-Host "Updated: $file"
        } else {
            Write-Host "Pattern not found in: $file"
        }
    } else {
        Write-Host "File not found: $file"
    }
}
