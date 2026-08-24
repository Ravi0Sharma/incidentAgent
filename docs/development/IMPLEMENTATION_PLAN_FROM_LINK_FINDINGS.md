# Implementationsplan från link findings

Skapad: 2026-07-28  
Underlag: `LINK_FINDINGS.md` och `output/hadoop-openai-baseline.json`

## Nuläge

OpenAI-kopplingen fungerar och modellen följer evidenskontraktet. Den
balanserade åtta-case-baselinen gav 8/8 giltiga API-svar och 100 procent
giltiga evidensciteringar, men bara 12,5 procent coverage. Problemet är
lokaliserat före modellen:

```text
rålogg                         7/8 hade terminal status
  ↓ sampling                   0/7 behöll terminal status
  ↓ gruppering/evidenspack     ytterligare nätverkssignal försvann
  ↓ OpenAI                     7 ärliga abstentions, 1 korrekt klass
```

Målet för nästa etapp är en mätbar och informationsbevarande pre-review-
pipeline. Postmortem, review-minne, remediation och hostad deployment ingår inte i denna
etapp.

Status 2026-07-28:

- P0 scorecard/recoverability: klar;
- P1 lifecycle-aware sampling: klar;
- P2 evidenspack/invarianter: klar;
- P3 typad korrelation/proveniens: klar;
- P4 åtta development + 47 final holdout: klar och gates passerar;
- P5 HDFS_v1 + OpenStack, första nya datasetloopen: klar;
- P6 pre-review production hardening: aktiv; typad Hadoop-review körd på
  samtliga 55 facitfall.

## Viktig evalprincip

De åtta redan analyserade applikationerna är nu utvecklingsfall och får inte
rapporteras som ett nytt blindtest efter tuning. De återstående 47 Hadoop-
applikationerna är final holdout för en enda jämförelsekörning när P0–P2 är
klara.

Datasetetiketten beskriver injicerad störning, inte nödvändigtvis att varje
jobb misslyckades. Ett jobb kan exempelvis nå `SUCCEEDED` och ändå innehålla
en senare “lost node”-signal. Därför ska vi mäta två olika saker:

- `fault_class_recoverability`: finns klasskiljande evidens i råkällan?
- `pipeline_recovery`: överlevde den evidensen till evidenspack och modell?

En ärlig abstention ska räknas som rätt beteende när råkällan själv inte gör
fallet avgörbart.

Om en injicerad abnormal label inte är återvinningsbar men råloggen visar att
jobbet nådde `SUCCEEDED`, är `normal` ett evidensgrundat observerat jobbutfall
men inte en korrekt rekonstruktion av den dolda fault labeln. Rapporten ska
därför markera `data_ceiling_limited` och redovisa dataset-exact accuracy
separat från hallucination/grounding.

## P0 – gör evalen diagnostisk

### 0.1 Stage-by-stage scorecard

Implementera en rapport per applikation för:

- antal råa och parsade events;
- antal events efter sampling;
- tidsmässig täckning över hela jobbintervallet;
- lifecycle-/terminal-events i rålogg, sample, grupper och evidenspack;
- direkta maskin-, nätverks- och disk-signaler i samma fyra steg;
- antal unika eventfamiljer före och efter sampling;
- vilka evidens-ID:n som tappas mellan två steg.

Acceptans:

- samma case kan följas från rå rad till LLM-citerbart ID;
- scorecard visar det första steg där varje känd signal försvinner;
- labels används först efter att pipelineartefakterna har skapats;
- ordningsinvarians och nuvarande parsergate fortsätter passera.

### 0.2 Definiera recoverability utan label-läckage

Skapa en versionssatt katalog av generella observerbara signalfamiljer, till
exempel:

- job lifecycle/state transition;
- node/worker availability;
- network reachability/transport;
- storage capacity/write failure;
- generic application error.

Katalogen ska matcha observerad text och typ, aldrig titta på facit för att
välja vad som inkluderas.

Acceptans:

- varje träff har `signal_family`, `source_event_id`, matchmetod och version;
- ett case får `raw_recoverable=true` endast från rå evidens;
- indirekta symptom markeras som sådana och blir inte root cause.

## P1 – fixa sampling utan en hård error-gräns

### 1.1 Lifecycle-aware sampling

Utöka `representative_sample` med reserverade platser för:

- första och sista events;
- terminala state transitions och completion/failure;
- första, peak och sista event i varje högsignalsfamilj;
- sällsynta feltyper och state transitions;
- tidsstratifierad bakgrund för kontext.

Använd en total budget och relativa kvoter, inte en regel som “fler än N
errors”. Om en familj är mycket stor ska representanter och exakt total count
bevaras.

Acceptans på de åtta utvecklingsfallen:

- terminal status behålls i minst 6/7 fall där den finns i råloggen;
- den observerade “lost node”-signalen behålls;
- båda observerade nätverkssignalerna behålls;
- sample håller konfigurerad maxstorlek;
- tidsmässig täckning och signal diversity försämras inte mot baseline.

### 1.2 Sampling-regressioner

Lägg fixtures för:

- normalt jobb med ett irrelevant IOException;
- terminal `SUCCEEDED` nära slutet;
- “lost node” efter en tidigare success-transition;
- stor `NoRouteToHostException`-burst;
- få nätverksevents som konkurrerar med vanligare loggrupper;
- extern fault label utan direkt felsträng.

Acceptans:

- testen verifierar exakt vad som ska bevaras, inte en viss intern algoritm;
- om budgeten är för liten rapporteras bortval och sampling bias explicit.

## P2 – gör evidenspacken komplett och självkonsistent

### 2.1 Lifecycle summary

Lägg en egen sektion i evidenspacken:

```text
job state transitions
terminal status
first observed
last observed
supporting event IDs
```

Normal får bara påstås med positiv terminal evidens. Ett varnings-event får
inte ensamt göra ett normalt jobb onormalt.

### 2.2 Signal-family representatives

Ersätt “en toppgrupp per service + en sällsynt grupp” som enda urval med minst
en representant per observerad relevant signalfamilj, inom en hård
tecken-/tokenbudget.

Prioritetsordning:

1. direkt klasskiljande evidens;
2. terminal/lifecycle-evidens;
3. motsägande evidens;
4. temporal kontext;
5. frekventa bakgrundsgrupper.

Acceptans:

- de 16 samplade nätverkseventen i det andra nätverksfallet ger minst ett
  citerbart event i evidenspack;
- varje sammanfattad count anger om den avser rådata eller sample;
- modellen kan inte få intrycket att ett sample-count är ett globalt count.

### 2.3 Kontraktsinvarianter

Inför fail-closed checks före LLM:

- `sufficient evidence` kräver minst en giltig kandidat;
- varje kandidat måste ha supporting evidence ID;
- kandidatens kategori måste vara förenlig med signalfamiljen;
- observerad samtidighet får inte markeras som verifierad orsak;
- `observed`, `deterministic_derived` och `model_inferred` hålls isär;
- okänd eller motsägande status ger abstention, inte en reservhypotes.

Det nu observerade felet “evidence sufficient + no deterministic candidate”
ska bli ett regressionstest.

## P3 – korrelation som separata lager

Implementera och utvärdera fyra relationstyper var för sig:

| Lager | Fråga | Minsta bevis |
|---|---|---|
| Temporal | Händelserna låg nära i tid? | tidsstämplar och fönster |
| Entity/service | Gäller de samma jobb, container, host eller service? | normaliserad entity |
| Topology/dependency | Finns en känd beroenderelation? | observerad/configurerad edge |
| Change/deploy | Föregicks symptomet av relevant förändring? | change-ID och tidsrelation |

Varje edge får:

- `provenance`;
- `method`;
- supporting event IDs;
- direction;
- confidence;
- alternativ förklaring eller missing evidence.

Ingen sammanvägd “causal score” införs innan varje lager har egna
precision-/retention-mått.

## P4 – återkörning och gates

### 4.1 Lokalt före betalda modellkörningar

Kör:

- hela testsviten;
- promptbudget;
- samtliga 55 fall genom stage scorecard utan LLM;
- de åtta utvecklingsfallen genom evidenspack-regressionen.

### 4.2 OpenAI development rerun

Kör samma åtta utvecklingsfall med oförändrad modellprompt och
`gpt-5.6-luna`.

Gates:

- 8/8 provider success;
- 100 % schema/claim-contract;
- 100 % giltiga evidens-ID:n;
- noll truth-läckage;
- raw-recoverable signal retention till evidenspack minst 90 %;
- inga säkra klasspåståenden på raw-unrecoverable fall;
- coverage rapporteras både totalt och endast på recoverable fall.

Ändra inte prompten och datapipelinen samtidigt i samma experiment.

### 4.3 Final holdout

Frys kod, signalkatalog, samplingpolicy, evidenspackversion och prompt. Kör
därefter de återstående 47 fallen en gång.

Rapportera:

- provider/schema/citation gates;
- recoverable coverage;
- selective accuracy;
- abstention på unrecoverable fall;
- per klass och workload;
- confusion matrix;
- latens och tokenanvändning;
- versions-ID:n för kod, data, prompt och modell.

Den finala gaten är inte en ensam accuracy-siffra. Förslag till första
acceptansnivå:

- minst 80 % korrekt klass eller korrekt abstention totalt;
- minst 75 % selective accuracy per recoverable klass med tillräckligt antal
  fall;
- minst 90 % abstention på fall utan klasskiljande råevidens;
- 0 unsupported evidence IDs och 0 kritiska kontraktsbrott.

Trösklarna är en initial evalpolicy, inte produktions-SLO:er.

## P5 – nya datakällor efter Hadoop

Datasetordningen är nu underställd miljögaten i
`TARGET_ENVIRONMENT_AND_DATA_PRIORITY.md`. Spark, Hadoop, HDFS, BGL och
OpenStack är evalkorpora och ska inte automatiskt bli produktens support scope.

När holdout-resultatet är förstått och målmiljön är ratificerad:

1. Välj ett replay-fönster från den avsedda applikationsstacken.
2. Lägg Rootly Apache endast om HTTP-/webbserverloggar motsvarar miljön.
3. Lägg Rootly OpenSSH endast om säkerhets-/SSH-incidenter ingår.
4. Härled egna source counts; lita inte på README-siffror.
5. Märk korpora utan incidentfacit som `no_root_cause_truth`.
6. Bygg därefter kontrollerade fault-injection-scenarier med explicit onset,
   orsak, symptom, irrelevant brus och expected evidence.
7. Utvärdera SREGym i en isolerad spike först efter statiska kontrakt.

Spark 2k-adaptern och dess grupperings-/abstentionstest är klara, men fortsatt
Spark-specifik fault-data och signalutveckling är parkerad. Kafka är också
villkorat senarearbete tills dess verkliga broker-/clientmiljö är känd.

Lokalt inventerade nästa dataset:

- `../HDFS_v1`, 1,7 GB, block-traces med `Normal`/`Anomaly`;
- `../OpenStack`, 59 MB, normalfiler samt abnormal logg med fyra märkta
  VM-instanser.

HDFS-labeln är binär anomaly, inte root cause. OpenStack har injicerade
VM-anomalier men kräver verifiering av hur instance-ID, tidsfönster och
observerad effekt hör ihop. Båda börjar därför som
parser/sampling/anomaly-retention-eval och får inte behandlas som RCA-facit.

### Resultat 2026-07-28

HDFS_v1:

- alla 575 061 blockspår lästes och matchades mot ett separat facit;
- 558 223 var märkta normal och 16 838 anomaly;
- 250 deterministiskt valda fall per klass gick genom
  representative sampling utan att etiketten exponerades för samplern;
- första/sista event och alla katalogiserade signalformer behölls i 500/500
  fall;
- genomsnittlig eventtyps-recall var 96,01 procent för anomaly och
  99,50 procent för normal.

OpenStack:

- 207 820 primära råloggrader parsades över tre filer; åtta
  fortsättningsrader bands till rätt föregående event;
- UUID och IP-adresser minimerades före pipelineartefakter;
- samplern hittade initialt bara 57–80 procent av distinkta
  högsignalsmönster;
- efter att `warning` och första/sista representant per normaliserad
  högsignalform reserverats blev retention 100 procent i alla tre filer;
- samtliga fyra märkta anomaliinstanser hittades, men 0/4 hade en direkt
  signal i den generella signalkatalogen. Det är en datagräns och ska ge
  abstention/mer insamling, inte en påhittad RCA.

Reproducerbara rapporter:

- `output/hdfs-v1-evaluation.json`;
- `output/openstack-evaluation.json`.

Ett miljömatchat replay-fönster och därefter kontrollerad fault injection är
nästa relevanta breddning. Rootly Apache/OpenSSH används bara om HTTP- eller
SSH-loggar ingår i den ratificerade supportgränsen. Inget av detta blockerar
fortsatt härdning av den nu mätbara pre-review-pipelinen.

## P6 – pre-review production hardening

Aktiv ordning efter datasetloopen:

1. explicita runtime-modes och fail-closed shadow/production;
2. källspecifikt schema, datakvalitet och rekonstruerbar query-proveniens;
3. komplett evidensdriven expansionsloop med revisions- och stopporsak;
4. total incidentdeadline samt modellens usage-/kostnadsledger;
5. strikt typade hypoteser och oberoende claim-level grounding;
6. E2E-matris för success, korrekt abstention, källa nere, provider nere och
   budget slut.

Steg 1 är nu delvis klart: `shadow` och `production` kräver autentiserade
HTTPS-källor, hosted modellnyckel, MySQL, redaction, explicita CORS-origins och
avstängd extern publicering. Osäkra kombinationer stoppar startup och Phoenix
kan endast aktiveras i `local`.

Steg 2 är lokalt implementerat och verifierat:

- `connector-provenance/v2` med explicit källschema, connectorversion,
  sanerad backend och stabilt query-ID;
- `incident-query/v1` beskriver operation, service, allowlistade filter,
  tidsfönster, limits, sampling och replay-template;
- `source-quality/v1` mäter input, usable, quarantine, parse/source errors,
  dubletter, saknade fält/tider, timestamp quality, event range och freshness;
- felaktiga logg-/deploytidsstämplar och saknade obligatoriska fält
  karantänas före pipeline;
- PromQL tas bort från metric records efter collection;
- query-ID och source schema följer loggar genom normalisering, gruppering,
  timeline och evidence graph;
- review-vyn visar läsbara source cards med sanerad replay-specifikation.

Steg 3 är lokalt implementerat och verifierat:

- initial insamling sker på alerttjänsten och expansion tillåts bara inom
  observerad eller godkänd scope;
- `investigation-loop/v1` begränsar rundor, scoped services, tidsfönster,
  tool calls/remote units, retained result bytes och total expansionstid;
- nya tool samples går genom samma normalisering, redaction, deduplicering,
  detektion, korrelation och kandidatpoäng som initiala loggar;
- varje runda skapar en append-only `investigation-revision/v1` med query-ID,
  kompakt resultatstatus, nya records, kandidatranking och beslut;
- grafen kör en ny semantisk evidensrunda endast när ny evidens fortfarande
  lämnar ett konkret gap och budget återstår;
- explicit stopporsak är `enough_evidence`, budgetgräns,
  `source_unavailable` eller `safe_abstention`;
- review-HTML visar expansionsutfall, revisioner och senaste query-ID:n.

Steg 4 är implementerat för pre-review-flödet:

- `incident-analysis-deadline/v1` startas före collection och följer
  incidentens checkpointade state;
- nya OpenAI-anrop får högst återstående incidenttid som request-timeout och
  nekas helt efter deadline;
- targeted tool calls nekas också efter incidentdeadline;
- `model-usage-ledger/v1` summerar provider-rapporterade input-, output- och
  totaltokens per lyckat semantic/interpretation-anrop;
- provider request-ID och modellnamn sparas per anrop;
- kostnad visas endast som en konfigurerad uppskattning när explicita
  per-miljon-token-priser har satts; annars står ärligt
  `pricing_not_configured`;
- deadline och ledger följer med till immutable analysis snapshot och syns i
  review-HTML.

Initiala connectors har fortsatt egna bounded timeout/retry-policyer. Hård
kooperativ cancellation mitt i ett redan startat connectoranrop och en
faktureringsavstämd kostnadsledger är fortfarande produktionshärdning, inte
något den lokala ledgern påstår sig lösa.

Steg 5 är implementerat för interpretation före review:

- modellen måste lämna `model-interpretation/v1` JSON; fri Markdown accepteras
  inte längre som sanningskälla;
- noll till tre hypoteser måste matcha befintliga deterministiska kandidater;
- varje cause/mechanism/impact-claim har typ, status och evidence-ID:n;
- `claim-grounding/v1` körs deterministiskt efter modellen och före rendering;
- okända eller kandidat-inkompatibla evidence-ID:n stoppar hypotesen;
- kausalitet märkt `observed` nedgraderas till `hypothesis`, och en mekanism
  kräver en validerad cross-event semantic link för att ens visas som inferens;
- source failure och truncation begränsar confidence;
- osäkra restart/rollback-liknande steg tas bort om de inte är proposal med
  explicit approval;
- TL;DR, hypotesrubrik, faktarader och blast-radius-gräns renderas från
  validerad/deterministisk data, inte modellens fria formulering;
- structured interpretation och grounding-rapport sparas i analysis snapshot
  och visas i review.

Verifiering 2026-07-28:

- 145/145 tester passerar, inklusive claim-grounding-, observations-/impact-,
  burst- och Hadoop typed-review-tester;
- pre-review-sviten passerar 8/8;
- promptbudgeten passerar; evidence pack är 3 773/6 000 tecken.

Steg 6 är medvetet nedskalat till de tre datanära reviewfallen:

1. tydlig evidens ger en supported review;
2. otillräcklig evidens ger korrekt abstention;
3. två jämna kandidater ger expansion-rekommendation och därefter abstention
   när ingen diskriminerande evidens tillkommer.

Mockade OpenAI-, timeout- och connection-fel är parkerade i
`DEFERRED_CONNECTION_FAILURE_TESTS.md`. Cross-service A→B/payments är inte en
aktiv E2E-gate; det befintliga testet får ligga kvar som billig regression men
styr inte nästa arbetssteg.

Körning 2026-07-28:

- 3/3 valda reviewscenarier passerade;
- tydlig evidens gav `supported_review`, korrekt toppkandidat och
  `enough_evidence`;
- otillräcklig evidens gav `abstained_review` och `safe_abstention`;
- två exakt jämna kandidater gav gap `0`, expansion rekommenderades och
  resultatet blev säker abstention när inget diskriminerande tillkom;
- inga okända evidence-ID:n överlevde grounding;
- providerläget var degraded och gav noll rapporterade modellanrop/tokens.
  Detta är tydligt markerat i rapporten och connection-utredningen är
  medvetet parkerad.

Artefakter:

- `output/review-scenarios/report.json`;
- `output/review-scenarios/review-clear-evidence.html`;
- `output/review-scenarios/review-insufficient-evidence.html`;
- `output/review-scenarios/review-tied-candidates.html`.

### Reviewflödets beslutsgräns 2026-08-09

Reviewsteget har nu optimerats innan mer datasetarbete:

- API och statisk HTML använder samma review-gate;
- interpretation quality och claim grounding måste båda passera;
- endast hypotesranker som också finns i den sparade deterministiska
  kandidatrevisionen kan erbjudas för approval;
- en provider-degraderad men fullt validerad deterministisk analys kan granskas
  med en synlig varning i stället för att felaktigt bli `analysis unavailable`;
- abstention, misslyckad grounding och osparade hypotesranker blockerar fortsatt
  approval;
- reviewn visar en begränsad ordnad tidslinje och analysen före beslutsknapparna;
- teknisk JSON, modellbudget, verktygsspår och full evidence pack ligger bakom
  en expanderbar detaljsektion.

De tre reviewscenarierna kontrollerar nu även HTML-beteendet: supported review
har en giltig approval-kontroll, medan båda abstentionfallen saknar den. 3/3
passerar utan OpenAI-anrop. Hela regressionssviten passerar 191/191.

Nästa men inte ännu implementerade post-review-steg är ett
`postmortem-quality/v1`-kontrakt, inte visuell finputsning. Det ska validera att
utkastet använder exakt godkänd analysrevision, separerar verifierade fakta från
hypoteser, citerar kända evidence-ID:n för impact/timeline/root cause, behåller
okända värden som okända och faller tillbaka till ett ärligt internt utkast om
modellen bryter kontraktet. Separat exact-draft publish approval ligger senare.

### Hadoop-facit mot den typade reviewgränsen

Parent-folderns `../Hadoop/abnormal_label.txt` är nu inkopplad som held-out
evaldata mot samma kandidat-, interpretation- och groundinggräns som reviewn.
Facit joinas först efter att pipeline- och reviewartefakterna är färdiga.

Den första typade körningen lokaliserade fem supported facit-mismatchar. Efter
entity/impact-passet kördes samtliga 55 applikationer om. Den aktuella körningen
gav:

- 100 procent grounding pass rate;
- 0 okända evidence-ID:n och 0 unsupported predictions;
- 32,73 procent exact injected-label accuracy;
- 100 procent exact accuracy i de 18 fall där incident-impact är
  återvinningsbar;
- 98,18 procent korrekt utfall eller ärlig abstention;
- 0 supported facit-mismatchar;
- 15 recovered faults bevarade som observation-only;
- 25 explicita konflikter mellan den enda injektionslabeln och observerade
  loggsignaler/jobbutfall.

Signaltäckningen sätter nu den tydliga datagränsen: `machine_down` 13/28,
`network_disconnection` 5/7, `disk_full` 0/9 och positiv normal/successignal
10/11. Det går inte att prompta fram de saknade disk-signalerna. Nästa
förbättring är entity- och tidsfönsterkoppling för samtidiga signaler samt en
storage-/hostkälla för `disk_full`.

Direkta katalogsignaler skapar först `observed-signal/v1`. Hashade workload-
och execution-ID:n, `impact-assessment/v1`, `signal-impact-link/v2` och
`event-burst/v1` bevarar scope,
operationseffekt, recovery och burst utan råa dataset-ID:n. En recovered signal
utan negativ lifecycle-impact stannar som observation-only. Endast
impact-berättigade observationer får skapa label-blinda kandidat-hypoteser med
stabila evidence-ID:n. De är alltid märkta
`root_cause_status=not_established` och
`causal_status=requires_verification`. Materiellt jämna kandidater eller flera
observerade felkategorier ger abstention.

Artefakter:

- `output/hadoop-entity-impact-all-55.json`;
- `output/hadoop-entity-impact-pilot.json`;
- `output/hadoop-entity-impact-pilot/*.html`.

### OpenAI-gate efter entity/impact-passet

Ett nytt label-exkluderat liveprov kördes på åtta representativa fall mot
`gpt-5.6-luna`. Transport och structured output fungerade i 8/8 fall.
Råmodellen följde boundary-beslutet i 7/8 fall; konkurrensfallet försökte
välja en maskinkandidat trots deterministisk abstention.

Detta kontraktshål är nu stängt i `claim-grounding/v1`: en modell får inte
återaktivera kandidater när den deterministiska bedömningen har satt
`abstain=true`. De frysta modellsvaren omgroundades utan nya anrop och gav:

- 8/8 korrekta groundade boundary-beslut;
- 100 procent abstention för observation-only, konkurrens och saknad evidens;
- 0 supported facit-mismatchar;
- 0 okända evidence-ID:n;
- ett känt men claim-inkompatibelt outcome-ID som avvisades säkert.

Nästa implementation inom P6 är därför:

1. [x] Lägg till typad policy för impact-claims: skilj orsakens supporting-ID:n
   från outcome/contradiction-ID:n utan att låta outcome bevisa orsak.
2. [x] Lägg explicita entity- och tidsrelationer på befintliga Hadoop-fall.
3. [ ] Utöka facit först när en befintlig källa inte kan svara på
   `observed_faults`, `affected_entity`, onset/fönster och `job_outcome`;
   bygg inte ett större syntetiskt corpus nu.
4. Behåll både råmodellens och det groundade slutbeslutets mått i varje
   regression; skyddslagret får inte maskera försämrat modellbeteende.
5. [x] Kör samma kontrakt mot HDFS_v1/OpenStack.
   - [x] Implementera label-fri, peer-relativ operation-duration med
         baseline-proveniens och utan fast sekundgräns.
   - [x] Implementera explicit HDFS block-I/O failure som operation impact
         utan root-cause-promotion.
   - [x] Kör fyra blindade OpenAI-smokefall på de nya evidenspaketen:
         4/4 provider/schema/grounding/boundary, 0 hypoteser, 0 okända
         evidens-ID:n och 0 non-read-only-förslag.
   - [x] Separera successful completion från faktisk recovery i
         latency-observationens modellkontext.
   - [x] Kör utökad OpenAI-regression: 12/12 provider/schema/raw
         boundary/grounding/final boundary; 4/4 latencyfall uttrycktes som
         successful-but-slow och 0 recovery-wording-defekter.
6. [ ] Kör senare Apache/OpenSSH efter dataset-specifik source review.

Hadoop-resultat efter `impact-assessment/v1`:

- 100 procent impact-contract pass rate på 55 fall;
- 63/63 direkta observationer typade;
- 15 established och 48 contradicted impact-bedömningar;
- 18/18 impact-avgörbara fall exakta;
- 0 supported mismatchar, entity-mismatch-kandidater, pre-signal-kandidater
  eller okända roll-ID:n.

HDFS_v1/OpenStack-resultat:

- 40 HDFS-blockfall och 16 OpenStack-VM-fall passerade grounding och
  impact-kontrakt till 100 procent;
- HDFS gav 9 storage-observationer i valda anomaly-fall. Efter
  implementationen etablerar de 6 explicita I/O-felen
  `block_operation_failed`, medan 3 metadatafall stannar `not_established`;
- full label-last audit bekräftade OpenStack-duration över 2 064 kompletta
  traces: alla fyra anomalier låg i minst 98,46:e percentilen mot samma
  source-cohort och minst 96,15:e percentilen inom samma timme;
- full HDFS-audit över 575 061 traces visade att `E7` fanns i 3 303 fail och
  0 success, medan metadatahändelserna `E20/E28` även fanns i 231 success;
- den peer-baseline-baserade `operation_latency_deviation`-featuren är
  implementerad och gav 4/4 anomaly samt 0/12 normal i OpenStack-omkörningen;
- den snäva explicita I/O-fel → `block_operation_failed`-länken är
  implementerad och gav 6 etablerade HDFS-operation impacts;
- HDFS metadata stannar observation-only och ingen labelkalibrerad hård
  tidsgräns eller root-cause-regel infördes;
- båda rapporterna passerar grounding och impact-kontrakt till 100 procent,
  med 0 root-cause-kandidater från de nya features.

Artefakter:

- `output/hadoop-entity-impact-openai-8.json`;
- `output/hadoop-entity-impact-openai-8/index.html`;
- `output/hadoop-impact-assessment-v1-all-55.json`;
- `output/hdfs-v1-impact-generalization.json`;
- `output/openstack-impact-generalization.json`;
- `output/distributed-feature-audit.json`;
- `output/distributed-feature-audit.html`;
- `output/distributed-openai-smoke-4.json`;
- `output/distributed-openai-smoke-4/index.html`;
- `output/distributed-openai-eval-12.json`;
- `output/distributed-openai-eval-12/index.html`;
- `scripts/evaluate_distributed_impact.py`;
- `scripts/audit_distributed_features.py`;
- `scripts/evaluate_distributed_openai.py`;
- `utils/operation_duration.py`;
- `scripts/evaluate_hadoop_entity_impact_openai.py`.

## Senare, inte i denna plan

De här punkterna är intressanta och ska inte tappas bort. De är en explicit
att-göra-lista efter att P6 pre-review-gates är gröna:

- [ ] Postmortem-generering och finputsning, byggd enbart från den godkända
      typade hypotesen och exakt evidensrevision.
- [ ] Historiskt review-minne med proveniens, rättning, expiry och
      filter-first retrieval; tidigare incidenter får vara förslag, aldrig
      facit.
- [ ] Runbook-/remediation-förslag i read-only/dry-run-läge.
- [ ] Rollback/restart endast som separat, explicit godkänd åtgärd med scope,
      timeout, rollback-plan och audit trail.
- [ ] Ett miljömatchat replay-fönster med signal, brus och observerat utfall.
- [ ] Rootly Apache och OpenSSH endast om deras loggdomäner ingår i
      supportgränsen.
- [ ] SREGym som isolerad spike efter att statiska och fault-injection-baserade
      kontrakt passerar.
- [ ] Tool calling mot externa system först med allowlist, budget, audit och
      fail-closed policy.
- [ ] Hostad deployment sist, efter lokala och shadow-relaterade gates.

En eventuell driftetapp startar först när den lokala pipelinen har passerat
holdout-gates och secrets har roterats och placerats i vald secret manager.

## Säkerhetsåtgärd före nästa externa körning

API-nyckeln låg i `.env.example`. Den har flyttats till en git-ignorerad
lokal `.env` med filrättighet `0600`, och exempelvärdet är återställt till en
placeholder. Rotera ändå nyckeln i OpenAI-kontot eftersom den tidigare låg i
en fil avsedd att kunna delas.

## Rekommenderad arbetsordning

```text
P0 scorecard/recoverability
  → P1 lifecycle-aware sampling
  → P2 evidence-pack contract
  → P3 typed correlation
  → P4 local + 8 dev + 47 holdout
  → P5 HDFS_v1/OpenStack
  → P6 pre-review production hardening
  → Hadoop typed-review: entity/time-window + disk-källa
  → OpenAI entity/impact-gate
  → typad impact-policy + kontrollerade scenariofacit
  → Apache/OpenSSH + kompletterande kontrollerade scenarier
  → review/remediation
  → framtida hosting vid behov
```
