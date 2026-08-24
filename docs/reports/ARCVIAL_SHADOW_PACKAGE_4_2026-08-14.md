# Arcvial shadow paket 4 — runtime-bevis 2026-08-14

## Beslut och avgränsning

Den lokala kod- och MySQL-delen av paket 4 är klar: API och worker är separata
processer, workern kör kontinuerligt, aktiva jobb förnyar lease, ett
incidentlås förhindrar samtidiga revisioner, signaler dränerar aktivt jobb,
alla jobbingångar använder ett gemensamt kötak och utgångna leases kan tas över
efter processkrasch.

Detta är inte ett påstående om att en hostad produktionsmiljö är färdig.
Multi-host-deploy, faktisk processrestart i staging, last/fairness och
databasdrift hör fortfarande till paket 5, 7 och 9.

## Implementerad runtimegräns

- API:t kör inte köjobb när `API_DRAIN_JOBS=false`.
- `scripts/run_worker.py` är en separat kontinuerlig worker-entrypoint och
  vägrar starta om API-drain är aktiverad.
- `incident_jobs` och `incident_job_locks` leasas och förnyas atomiskt. Endast
  ett jobb per incident kan vara aktivt.
- `SIGINT`/`SIGTERM` stoppar nytt arbete och låter aktivt jobb avslutas före
  worker-exit.
- `incident_workers` innehåller durable process-heartbeats. `/readyz` kräver en
  färsk running-worker när API-drain är avstängd.
- `MAX_PENDING_JOBS` skyddar alertintag, reprocess och dead-letter replay.
  Avvisning ger 503/`Retry-After` i API:t och transaktionen lämnar inget
  fristående event.
- Shadow/production-konfiguration validerar separation, lease/heartbeat,
  worker poll/staleness och positivt kötak före start.

## Direkt process- och databasbevis

Bevisningen nedan kördes mot lokal MySQL 8.4 med externa writes, LLM och Phoenix
avstängda. Testsviten användes inte som primärt acceptansbevis.

1. API:t startades ensamt med `API_DRAIN_JOBS=false`. Incident `INC-100052`
   accepterades som jobb `347`; SQL visade `pending`, försök 0 och noll
   analysrevisioner. API-processen utförde alltså inte jobbet.
2. `scripts/run_worker.py` startades i en separat OS-process. Samma jobb blev
   `completed`, försök 1, fick en analysrevision och hade noll kvarvarande
   incidentlås.
3. Workern fick `SIGINT` efter jobbet. Loggen innehöll både `worker_started` och
   `worker_stopped`, och processen avslutades med exitkod 0.
4. Med API:t igång men workern stoppad svarade `/readyz` 503 med
   `worker.status=unavailable`. Efter separat worker-start svarade samma endpoint
   200 med `active_workers=1` och färsk MySQL-`last_seen`.
5. `scripts/verify_worker_runtime.py` körde direkt fault injection. Jobb `355`
   flyttade lease från `14:38:44.372498` till `14:38:45.017268`; incidentlåset
   följde exakt samma nya sluttid. Efter completion var låset borttaget.
6. Jobb `356` leasades av `runtime-verifier-crashed` på försök 1. Processen
   slutade förnya och en recovery-worker tog över efter faktisk lease-expiry på
   försök 2. Slutstatus blev `completed` och låset var borttaget.
7. Ett nollställt kötak avvisade en syntetisk ingress och SQL visade noll
   orphan-events.
8. En slutlig reprocess hittade att jobbets versionerade run-context inte
   följde med till analysrevisionen: jobb `378` bar
   `package4-final-handler`, medan revision 2 felaktigt fick standardversionen.
   Flödet korrigerades så `code_version`, `prompt_version`, `model_version` och
   pipeline-manifest skickas till den immutabla analysrevisionen. Ett nytt jobb
   `379` avslutades på försök 1; SQL visade revision 3 med exakt
   `package4-context-fix` / `package4-proof` / `skip-llm` och noll kvarvarande
   lås.

Verifieraren är avsiktligt spärrad till `local`/`development` och får inte
köras som fault injection i shadow eller produktion.

## Sekundärt regressionsbevis

De fokuserade MySQL- och konfigurationskontrollerna passerade 31/31 efter den
direkta körningen. Därefter passerade hela `scripts/quality_gate.py`: 291/291
tester, Ruff, scoped mypy, compileall, promptbudget och repository secret scan.
Branch coverage var 74,5 procent för hela repot, 82,2 procent för kärnscopet
och 97,2 procent för säkerhetsscopet. Detta är regressionsskydd, inte ersättning
för process- och SQL-observationerna.

## Krävs innan paketet får kallas stagingverifierat

1. Kör API och worker som två verkliga deploy-services mot samma staging-MySQL.
2. Döda worker-process/container mitt i ett långvarigt jobb utan att ändra DB
   manuellt; verifiera takeover först efter lease-expiry och exakt en revision.
3. Skicka `SIGTERM` under ett aktivt jobb och bevisa drain inom plattformens
   shutdown-grace-period.
4. Kör burst och backlog större än det normala trafikfönstret; verifiera 503,
   återhämtning och ingen starvation mellan incidenter.
5. Larma på stale worker, ködjup, äldsta jobb, retry och dead letter i det
   gemensamma observability-backendet.

Tills dessa fem punkter passerar är paket 4 lokalt komplett men inte ett
produktionsgodkännande.
