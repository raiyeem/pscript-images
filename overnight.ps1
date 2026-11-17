$urls = @(
  "https://foremarket.se/en/explore?category=iron",
  "https://foremarket.se/en/explore?category=putter",
  "https://foremarket.se/en/explore?category=fairway-wood",
  "https://foremarket.se/en/explore?category=hybrid",
  "https://foremarket.se/en/explore?category=wedge",
  "https://foremarket.se/en/explore?category=bags",
  "https://foremarket.se/en/explore?category=trolleys",
  "https://foremarket.se/en/explore?category=men-apparel",
  "https://foremarket.se/en/explore?category=shoes",
  "https://foremarket.se/en/explore?category=balls"
)

$log = "overnight_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
"Starting overnight crawl. Log: $log" | Tee-Object -FilePath $log -Append

foreach ($url in $urls) {
    "`n===== $(Get-Date -Format 'HH:mm:ss') START $url =====" | Tee-Object -FilePath $log -Append
    .\venv\Scripts\python.exe -u scrape.py --crawl-and-save $url --save 2>&1 | Tee-Object -FilePath $log -Append
    "===== $(Get-Date -Format 'HH:mm:ss') END $url exit=$LASTEXITCODE =====" | Tee-Object -FilePath $log -Append
}

"`nAll categories attempted. Finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')." | Tee-Object -FilePath $log -Append