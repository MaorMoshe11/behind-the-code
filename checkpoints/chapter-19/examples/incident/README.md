# Incident evidence: "I deleted a conversation and lost my notes"

Real logs and metrics from staging (my-agent 0.13.0, notes-service 0.3.0), captured while
it happened. You do not need to run anything: diagnose from this folder alone.

## The report

Dana, a tester, wrote at 20:55 UTC:

> Around 20:44 I added a note to my "planning a trip to Haifa" conversation. It hung for a
> few seconds and said notes are unavailable. Then I deleted the whole conversation. It hung
> again and said: "The notes service is unavailable, so nothing was deleted. Try again later."
> (request c0dd82a75021404d805a82265d0c84cd). Fine, I thought, I'll try later. A few minutes
> later everything worked again, and the conversation is still there, as promised. But it
> has no notes at all. I had two notes in it before ("book the hotel", "buy sunscreen").
> Other people say the chat was fine for them.

## The files

| File | What it is |
|---|---|
| `api.log` | The chat api's log: `docker compose logs api --no-log-prefix`, JSON lines |
| `notes.log` | The notes service's log, JSON lines |
| `worker.log` | The usage worker's log, JSON lines |
| `metrics-before.txt` | The api's `/metrics`, taken shortly before the trouble |
| `metrics-after.txt` | The api's `/metrics`, taken after it was over |
| `ready.json` | What the api's `/ready` answered in the middle of it |
| `alerts.json` | Prometheus's alerts at the end (`/api/v1/alerts`) |

All times are UTC. Health checks are logged at DEBUG, so they are not in the logs. The notes
service was redeployed twice during this time; its log holds all three runs one after another
(they were collected before each redeploy, as a log aggregator would: Docker drops the logs of a
replaced container).

## Useful commands

```powershell
Get-Content examples\incident\api.log | Select-String "c0dd82a75021404d805a82265d0c84cd"
Get-Content examples\incident\notes.log | ForEach-Object { $_ | ConvertFrom-Json } | Format-Table time, level, message, duration_ms
Get-Content examples\incident\api.log | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object level -ne "INFO"
```

Questions: exercise 3 of chapter 13. Write down your hypothesis before you look at the code.
