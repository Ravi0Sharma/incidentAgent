# Link findings – AI-assisterad incidentanalys

Senast granskad: 2026-07-28

## Baseline-resultat 2026-07-28

Det blindade Hadoop → OpenAI-testet är genomfört med `gpt-5.6-luna`.
Maskinläsbar rapport finns lokalt i
`output/hadoop-openai-baseline.json`.

| Mått | Resultat |
|---|---:|
| API-svar | 8/8 |
| Schema och claim-kontrakt | 100 % |
| Giltiga evidens-ID:n | 100 % |
| Truth exponerad för modellen | 0 fall |
| Coverage, besvarad klass | 12,5 % |
| Abstention | 87,5 % |
| Selective accuracy | 100 % (1/1 besvarat fall) |
| Overall exact accuracy | 12,5 % |
| Tokenanvändning | 11 271 input + 2 687 output |

Kontraktsgaten passerade, men den diagnostiska datagaten föll. Det enda
besvarade fallet hade direkt `NoRouteToHostException`-evidens och
klassificerades korrekt som `network_disconnection`. I de övriga sju fallen
avstod modellen i stället för att gissa.

En efteranalys av de åtta fallen visar:

- terminal jobbstatus fanns i råloggen i 7/8 fall men försvann ur samplingen i
  samtliga sju;
- explicit “lost node”-signal fanns i råloggen för ett `machine_down`-fall men
  försvann ur samplingen;
- en andra nätverkssignal fanns kvar 16 gånger efter sampling men försvann när
  grupperna reducerades till evidenspack;
- de två `disk_full`-fallen saknade en enkel direkt `disk full`/`ENOSPC`-signal
  även i råloggen, så de kräver bättre kausal kedja eller är ärligt
  oklassificerbara från enbart nuvarande loggkälla;
- nuvarande evidenspack kan säga att deterministisk evidens är tillräcklig
  samtidigt som kandidatlistan är tom. Det är ett kontraktsfel före LLM.

Slutsats: OpenAI-integrationen är redo som utvärderingsinstrument. Pipelinen
är inte redo för produktionsklassificering. Nästa arbete ska förbättra
signalbevarande och evidenspack, inte göra modellen mer benägen att gissa.

## Hadoop development och final holdout 2026-07-28

Efter baseline implementerades stage-scorecard, versionssatta observerbara
signalfamiljer, lifecycle-aware sampling, tydlig job-lifecycle i
evidenspacken, fail-closed assessment-invarianter och typade
korrelationskanter med proveniens.

De åtta baselinefallen användes endast som development. De övriga 47
applikationerna kördes därefter som fryst holdout.

| Holdoutmått | Resultat |
|---|---:|
| API-svar efter en provider-retry | 47/47 |
| Schema och claim-kontrakt | 100 % |
| Giltiga evidens-ID:n | 100 % |
| Grounded response rate | 100 % |
| Recoverable coverage | 91,67 % |
| Recoverable selective accuracy | 90,91 % |
| Unsupported answer rate | 0 % |
| Dataset-exact accuracy | 42,55 % |
| Data-ceiling-limited fall | 23 |
| Label/evidence-konflikter | 24 |

Dataset-exact accuracy ska inte läsas som modellens groundingkvalitet. I 24
fall stödde råloggen en annan observerad fault eller ett lyckat jobbutfall än
datasetets enda injektionslabel. Exempel är `disk_full` med direkt
`lost node`, `machine_down` med connection timeout och `normal` med en direkt
nätverkssignal.

Nästa evaldataset behöver därför separata axlar för `injected_fault`,
`observed_faults` och `job_outcome`, eller multi-label.

Slutrapporter:

- `output/hadoop-openai-development-v4.html`
- `output/hadoop-openai-holdout-47-final.html`
- `output/hadoop-openai-holdout-47-final.json`
- `output/hadoop-stage-scorecard.json`

## Hadoop mot aktuell typad reviewgräns 2026-07-28

Hela Hadoop-facitfilen används nu även mot den nuvarande
`model-interpretation/v1` + `claim-grounding/v1`-gränsen. Körningen är
deterministisk och label-blind fram till scoring; datasetetiketten förekommer
inte i pipeline-state, kandidatval eller reviewartefakt.

| Mått | Resultat |
|---|---:|
| Fall | 55/55 |
| Grounding pass rate | 100 % |
| Okända evidence-ID:n | 0 |
| Unsupported prediction rate | 0 % |
| Exact injected-label accuracy | 32,73 % |
| Exact där incident-impact är återvinningsbar | 100 % (18/18) |
| Korrekt eller ärlig abstention | 98,18 % (54/55) |
| Supported facit-mismatchar | 0 |
| Recovered faults som observation-only | 15 fall |
| Facit/logg-konflikter | 25 |

Det viktigaste fyndet är att facit finns, men inte är ett fullständigt
kausalfacit. `abnormal_label.txt` anger injicerad störning per applikation.
Den anger inte separat observerade samtidiga fel, finalt jobbutfall, exakt
påverkad entity eller kausalt tidsfönster. Direkta råsignaler fanns för 13/28
`machine_down`, 5/7 `network_disconnection` och 0/9 `disk_full`; positiv
successignal fanns för 10/11 `normal`.

Tre designbeslut följer:

- en direkt felsignal blir en citerad, verifieringskrävande hypotes — aldrig
  automatiskt etablerad root cause;
- jämna konkurrerande kandidater ger abstention, inte godtycklig toppklass;
- `SUCCEEDED` redovisas som observerat jobbutfall och får inte bevisa att
  ingen störning inträffade.

Entity/impact-passet är nu implementerat:

- hashade `workload_id` och `execution_id` bevarar incidentlokal koppling utan
  att exponera råa Hadoop application/container-ID:n;
- `observed-signal/v1` skiljer direkt observation från orsakskandidat;
- `impact-assessment/v1` skiljer fault, impact, outcome, recovery och
  contradiction-evidens;
- `signal-impact-link/v2` länkar explicit operationseffekt, negativ lifecycle
  och senare recovery/success med entity- och tidsrelation;
- `event-burst/v1` bevarar onset, slut, duration, peak och total count utan att
  behandla repetitioner som oberoende kausal evidens;
- recovered signal utan negativ impact stannar som observation-only;
- flera observerade felkategorier ger abstention även när bara en kandidat
  annars skulle toppa.

Den lägre dataset-exact-siffran är avsiktlig: tidigare fem supported svar som
motsade facit har ersatts med säker observation/abstention. Alla 18 fall där
impact faktiskt är avgörbar klassificeras exakt.

Maskinläsbar rapport:
`output/hadoop-entity-impact-all-55.json`. Den balanserade HTML-piloten finns i
`output/hadoop-entity-impact-pilot/`.

## OpenAI-liveprov mot entity/impact-gränsen 2026-07-28

Åtta representativa Hadoop-fall kördes mot `gpt-5.6-luna` efter
entity/impact-passet. Facit användes för att välja regressionsfallen och för
scoring efter svaret, men skickades aldrig i evidenspack, instruktioner eller
modell-state. Två fall hade en impact-berättigad kandidat och sex skulle
abstain: recovery/observation-only, konkurrerande felkategorier, saknad
fel-evidens och normalfall.

| Mått | Resultat |
|---|---:|
| API-svar | 8/8 |
| Structured-output parse | 8/8 |
| Råmodellens boundary-beslut | 87,5 % (7/8) |
| Groundat slutbeslut | 100 % (8/8) |
| Observation-only abstention | 100 % |
| Konkurrerande signaler abstention efter grounding | 100 % |
| Saknad evidens abstention | 100 % |
| Supported facit-mismatchar efter grounding | 0 |
| Okända evidence-ID:n | 0 |
| Kända men claim-inkompatibla ID:n | 1 |
| Tokenanvändning | 22 494 totalt |
| Medianlatens | 5 016 ms |

Liveprovet hittade ett viktigt kontraktshål. I fallet med både maskin- och
nätverkssignal returnerade råmodellen `supported` trots att den
deterministiska bedömningen krävde abstention. Den tidigare groundern kunde
återaktivera en rankad kandidat även när hela kandidatbedömningen var spärrad.
`claim-grounding/v1` upprätthåller nu deterministisk abstention före all
hypotesvalidering. Det sparade modellsvarspaketet omgroundades lokalt utan nya
API-anrop; slutgränsen blev då korrekt i 8/8 fall. Råmodellens 7/8 bevaras som
ett separat mått så att skyddslagret inte döljer modellbeteendet.

Två andra beteenden var nyttiga:

- när modellen beskrev en observerad maskinsignal som orsak nedgraderade
  groundern den korrekt till en overifierad hypotes;
- en impact-claim citerade ett känt success-event som låg utanför hypotesens
  validerade supporting-set. ID:t var inte hallucinerat, men claim-inkompatibelt
  och claimen avvisades. Nästa kontraktsarbete bör avgöra om impact får citera
  ett separat typat outcome/contradiction-set utan att göra orsaken starkare.

Artefakter:

- `output/hadoop-entity-impact-openai-8.json`;
- `output/hadoop-entity-impact-openai-8/index.html`;
- `output/hadoop-entity-impact-openai-8/*.html`.

Beslut: OpenAI-kopplingen fungerar nu som ett användbart review- och
kontraktstest. Nästa steg är fortfarande mer kontrollerad data och ett
tydligare impact-evidenskontrakt, inte Railway, postmortem eller friare
modellklassificering.

### Impact-assessment och entity/time-pass

`impact-assessment/v1` är nu implementerat på de befintliga Hadoop-fallen,
utan ett nytt syntetiskt loggcorpus och utan nya OpenAI-anrop. Fault-, impact-,
outcome-, recovery- och contradiction-event har separata ID-roller.
`signal-impact-link/v2` anger dessutom `entity_match` och `time_relation`.

En första fullkörning fångade en viktig regression: en alltför strikt
execution-match tappade senare success på samma workload, vilket gjorde
recovered nätverksfel till falsk impact. Regeln korrigerades så att
workload-success får motsäga impact, medan ett adverse outcome från en annan
execution inte får etablera impact.

Efter korrigeringen är de tidigare säkerhetsresultaten oförändrade:

- 55/55 fall groundas;
- 18/18 impact-avgörbara fall är exakta;
- 0 supported facit-mismatchar;
- 0 okända evidens-ID:n eller impact-roll-ID:n;
- 15 observation-only-fall och 16 fall med recovery-kontext;
- 0 kandidater från entity mismatch eller outcome före signal.

Samtliga 63 direkta observationer har nu en validerad typad
impact-bedömning: 15 `established` och 48 `contradicted`. Coverage ökade inte
genom lösare regler.

Rapport: `output/hadoop-impact-assessment-v1-all-55.json`.

### Generalisering till HDFS_v1 och OpenStack

Samma label-exkluderade pipeline, `impact-assessment/v1` och grounding kördes
utan OpenAI mot två nya lokala korpusar. Deras facit är endast normal/anomaly,
inte feltyp eller root cause, så resultatet mäter kontrakt och signaltäckning
snarare än root-cause accuracy.

HDFS_v1:

- 40 hash-valda blockfall: 20 anomaly och 20 normal;
- adaptern skannade 11 175 629 källrader och hämtade 676 blockkopplade events;
- 9 direkta observationer hittades, samtliga i anomaly-fall:
  6 `storage_io` och 3 `storage_metadata`;
- alla 9 är `not_established`, med okänd impact/entity-relation och säker
  abstention; datasetet saknar kopplat workload-outcome för dessa blockfel;
- 0 signaler hittades i de 20 valda normalfallen;
- grounding och impact-contract passerade 100 procent, utan ID-läckor,
  okända evidens-ID:n eller ogiltiga kandidater.

OpenStack:

- 16 VM-fall: samtliga 4 märkta anomaly-instanser och 12 normalinstanser;
- 80 workload-lifecycle-signaler bevarades som outcome-kontext, inte faults;
- anomaly och normal har samma huvudsakliga lifecycle-sekvens, därför skapades
  inga orsakskandidater;
- en första label-blind feature var tydlig i urvalet: spawn duration skilde
  anomaly från normal, men detta behövde kontrolleras mot hela korpusen och
  source/time-confounders;
- ingen hård durationströskel har lagts till. En sådan regel behöver en
  versionssatt historisk baseline, miljö/smak-dimension och kalibrering utan
  eval-labels;
- grounding och impact-contract passerade 100 procent utan identifierarläckor.

Slutsats: kärnkontraktet generaliserar, men databehoven skiljer sig. HDFS
behöver blockfel → operation/outcome-länk. OpenStack behöver en baseline-aware
duration/latency-feature, inte fler regexar eller friare LLM-gissning.

### Full label-last feature- och confounder-audit

Beslutet verifierades därefter över hela den tillgängliga featurekorpusen.
Featurevärden, peers och händelseordning beräknades först. Facit anslöts endast
efteråt för score/association.

OpenStack:

- 207 820 loggrader gav 2 064 kompletta spawn traces;
- 4 märkta anomaly-traces hade faktisk median 37,302 s mot 20,384 s för
  1 868 märkta normal-traces;
- alla fyra anomalier låg även kvar som outliers mot de 195 övriga kompletta
  traces i samma abnormal-fil: 98,46–100:e percentilen och 1,47–2,51 gånger
  peer-medianen;
- samma kontroll inom starttimmen gav 96,15–100:e percentilen;
- fil- och tidsconfounding förklarar därför inte durationseffekten i denna
  korpus. Antalet märkta anomalier är fortfarande bara fyra, så fyndet
  motiverar en observation/impact-feature, inte en root-cause-regel;
- implementationen ska använda versionerad peer-baseline, minsta peerantal,
  percentile/ratio/MAD och baseline-proveniens. Ingen fast sekundgräns får
  kalibreras från dessa fyra labels.

HDFS_v1:

- samtliga 575 061 event traces analyserades: 16 838 `Fail` och 558 223
  `Success`;
- de typade storage-markörerna tillsammans förekom i 9 669 fail och 231
  success: precision 97,67 procent och recall 57,42 procent för datasetets
  blockutfall;
- `E7` (`storage_io`) förekom i 3 303 fail och 0 success. Minst 3 248 av
  dessa traces slutade direkt på `E7`; detta stödjer ett observerat
  block-I/O-operation failure, men inte en bakomliggande root cause;
- `E20` och `E28` (`storage_metadata`) förekom även i 219 respektive 12
  success-traces. De måste därför stanna som observationer om inte separat
  adverse outcome-evidens finns;
- generiska failure→senare-success-event var brusiga och ger inte en säker
  recovery-regel. Recovery måste knytas till samma blockoperation och
  eventspecifik semantik.

Implementationsresultat:

- `operation-duration-feature/v1` beräknar leave-one-out peers före
  facitanslutning och sparar `peer-duration-baseline/v1` med baseline-ID,
  cohort-dimensioner, peerantal, median, MAD, ratio, percentil, robust z och
  source-proveniens;
- policyn kräver minst 20 peers samt samtidiga relativa outlier-villkor;
  `fixed_seconds_threshold=null` och `labels_used=false` är kontraktsgates;
- OpenStack-omkörningen gav `operation_latency_deviation` för 4/4 anomaly och
  0/12 normal. Alla fyra fick `impact_status=established`, men 0
  root-cause-kandidater;
- HDFS-omkörningen gav 6/6 valda explicita `storage_io`-observationer som
  `block_operation_failed` med etablerad operation impact. Tre
  `storage_metadata`-observationer stannade `not_established`;
- samtliga HDFS/OpenStack-fall fortsatte att abstain från root cause:
  grounding och impact-kontrakt passerade 100 procent, utan okända
  evidens-ID:n, identifierarläckor eller osäkra baseline-features.

Beslutet är därmed implementerat. Resultatet är fortfarande endast verifierat
på den lokala OpenStack/HDFS-korpusen; fler miljöer behövs senare för
policykalibrering, inte för att ändra facit per dataset.

### Blindat OpenAI-smoketest efter distributed-impact-implementationen

Fyra pipeline-valda gränsfall kördes därefter mot `gpt-5.6-luna` via den
officiella Responses-API-endpointen. Testet använde Pydantic-baserad
Structured Output, `reasoning=low`, `store=false` och högst 1 200
output-tokens per fall. Datasetfacit anslöts först efter råmodellssvar och
grounding.

Fall:

- explicit HDFS block-I/O-fel;
- OpenStack utan direkt fault-observation;
- OpenStack peer-relativ latency-impact;
- HDFS metadataobservation utan etablerad impact.

Resultat:

- 4/4 provider-anrop och schema-parse lyckades;
- råmodellen abstainerade korrekt i 4/4 fall, alltså före grounding;
- 4/4 grounded boundary-beslut matchade och grounding passerade;
- 0 råa hypoteser, 0 okända evidens-ID:n och 0 non-read-only-förslag;
- modellen återgav den relevanta observationen i 4/4 fall;
- totalt 9 078 tokens rapporterades av providern; projektets prisfält är
  fortfarande `0`, så rapporten gör ingen påhittad dollarkostnadsberäkning.

Ett mindre semantiskt problem hittades i fyrakörningen. OpenStack-svaret
beskrev den framgångsrika men långsamma operationen som `recovered slow
operation latency`. Beslutet och abstentionen var korrekta, men `recovered`
var för oprecist.

Detta är nu korrigerat i datakontraktet:

- `succeeded` exponeras som `successful_completion`, separat från recovery;
- en slutförd duration är ett historiskt mätvärde som varken senare success
  eller `VM Resumed` kan motsäga;
- OpenStack-evidensen visar nu `impact=established`, `recovery=false` och
  `successful_completion=true`;
- en full OpenStack-omkörning behöll 4/4 anomaly och 0/12 normal latency-
  observationer.

Efter fixen kördes en utökad blindad OpenAI-regression med 12 fall: 4
OpenStack latency, 2 OpenStack utan direkt observation, 2 HDFS block-I/O,
2 HDFS metadata och 2 HDFS utan direkt observation.

- 12/12 provider-anrop, schema-parse, råa boundary-beslut, grounding och
  slutliga boundary-beslut passerade;
- 12/12 relevanta observationslägen återgavs;
- alla 4/4 latency-svar beskrev en långsam operation som slutfördes
  framgångsrikt;
- 0/4 latency-svar använde den felaktiga recovered-slow-formuleringen;
- 0 råa hypoteser, 0 okända evidens-ID:n, 0 non-read-only-förslag och inga
  ogrundade procentsatser;
- 27 451 tokens rapporterades av providern.

Artefakter:

- `output/hdfs-v1-impact-generalization.json`;
- `output/hdfs-v1-impact-generalization/index.html`;
- `output/openstack-impact-generalization.json`;
- `output/openstack-impact-generalization/index.html`;
- `output/distributed-feature-audit.json`;
- `output/distributed-feature-audit.html`;
- `scripts/audit_distributed_features.py`.
- `utils/operation_duration.py`.
- `output/distributed-openai-smoke-4.json`;
- `output/distributed-openai-smoke-4/index.html`;
- `scripts/evaluate_distributed_openai.py`.
- `output/distributed-openai-eval-12.json`;
- `output/distributed-openai-eval-12/index.html`.

## Beslut och användning

Det här dokumentet är en källbaserad backlog, inte en lista över redan
implementerade funktioner.

1. Kör först ett blindat Hadoop → OpenAI-baseline-test.
2. Behåll sanningsetiketten helt utanför pipeline och modellprompt.
3. Utvärdera transport, strukturerat svar, evidenscitering, abstention,
   täckning och klassificering separat.
4. Skapa en prioriterad implementationsplan från detta dokument först när
   baseline-testet visar att modellkopplingen är stabil och mätbar.
5. Railway och automatisk remediation ligger sist.

## Viktigaste slutsatsen

Det största problemet är fortfarande datakvalitet och evidensproveniens, inte
valet av LLM. Modellen bör få en liten, tidsordnad och spårbar evidenspack där
varje observation har ett stabilt ID. Den ska kunna avstå när underlaget inte
skiljer mellan exempelvis `machine_down`, `network_disconnection` och
`disk_full`.

En bra pipeline måste därför mäta vad som försvinner i varje steg:

```text
rålogg
  → parser
  → normalisering
  → sampling
  → gruppering
  → tidslinje och korrelation
  → evidenspack
  → LLM-tolkning
  → mänsklig review
```

End-to-end accuracy ensam kan inte visa vilket steg som förstörde signalen.

## Fynd per källa

### InvGate och PagerDuty

Källor:

- [InvGate – AI for incident management](https://blog.invgate.com/ai-for-incident-management)
- [PagerDuty – AIOps incident management](https://www.pagerduty.com/resources/aiops/learn/aiops-incident-management/)

Användbara idéer:

- Gruppera och deduplicera relaterade alerts innan en modell får materialet.
- Berika incidenten med service, ägare, miljö, tidigare incidenter och
  förändringar i stället för att skicka isolerade loggrader.
- Använd AI genom hela livscykeln: triage, undersökning, kommunikation,
  review och lärande.
- Koppla feedback från review tillbaka till regler, runbooks och utvärdering.
- Låt människor godkänna åtgärder med hög risk.

Begränsning:

Materialet beskriver främst produktmönster. Det bevisar inte att en viss
korrelationsmetod eller modell fungerar på vår data.

Konsekvens för projektet:

- Implementera inte “AI correlation” som en enda svart låda.
- Mät alert-deduplicering, enrichment och change-correlation separat.
- Vänta med review-minne och automatisk kommunikation tills pre-review-datan
  är pålitlig.

### AWS Generative AI Lens

Källa:

- [AWS – Generative AI-assisted incident response system](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-assisted-incident-response-system.html)

Användbara idéer:

- Separera ingestion, analys, modell, orchestration, presentation och
  governance i tydliga lager.
- Versionssätt prompt, modell, kod och utvärderingsdataset tillsammans.
- Behandla loggar, tickets och runbooks som opålitlig input som kan innehålla
  prompt-injektion eller känsliga uppgifter.
- Validera strukturerat modelloutput innan det får påverka senare steg.
- Börja med en mindre och billigare modell för högvolymssteg och eskalera bara
  svåra fall.
- Logga latens, tokenanvändning, feltyp och modellversion per körning.

Konsekvens för projektet:

- OpenAI-baselinen ska vara separat från produktionsgrafen.
- Output ska valideras mot ett schema och bara få citera kända evidens-ID:n.
- `store=false`, inga verktygsanrop och begränsad output används i första
  testet.
- Modellresultat får inte göra en osäker kausal relation till ett faktum.

### IncidentFox

Källa:

- [incidentfox/incidentfox](https://github.com/incidentfox/incidentfox)
- [Log sampling implementation](https://github.com/incidentfox/incidentfox/blob/1b6ffad4551da1eef1f2ca6ec254e9dd1816b002/sre-agent/.claude/skills/observability-loki/scripts/sample_logs.py#L41-L103)
- [Log statistics implementation](https://github.com/incidentfox/incidentfox/blob/1b6ffad4551da1eef1f2ca6ec254e9dd1816b002/sre-agent/.claude/skills/observability-loki/scripts/get_statistics.py#L43-L98)
- [Evaluation approach](https://github.com/incidentfox/incidentfox/blob/1b6ffad4551da1eef1f2ca6ec254e9dd1816b002/docs/EVALUATION.md#L33-L85)

Användbara idéer:

- Räkna felmönster och nivåer först; skicka inte hela loggströmmen till LLM.
- Arbeta hypotesdrivet: observation → hypotes → minsta verifierande sökning.
- Separera hämtning, statistik, sampling och modellanalys.
- Utvärdera agentbeteende med reproducerbara scenarier och fault injection.

Varningar:

- “Senaste N loggar” kan missa tidiga orsaker och ge en skev tidsbild.
- Hårda universella trösklar som 1 eller 5 träffar är inte överförbara till
  alla tjänster.
- Repositoriet arkiverades 2026-05-31 och är därför referensmaterial, inte en
  aktiv dependency.

Konsekvens för projektet:

- Behåll tidsstratifierad sampling och mät signal retention.
- Lägg inte till en hård “många errors”-gräns. Jämför hellre mot service,
  fönster, baseline, feltyp, samtidighet och påverkan.
- Lägg till felinjektion först när parser/sampling/evidenspack har mätbara
  delkontrakt.

### Akmatori

Källor:

- [akmatori/akmatori](https://github.com/akmatori/akmatori)
- [Gateway authorizer](https://github.com/akmatori/akmatori/blob/91599ad99d81fd6e4fab06a057e0064ac8e78187/mcp-gateway/internal/auth/authorizer.go#L30-L110)

Användbara idéer:

- Begränsa verktyg per incident och per fas.
- Skilj på analys, föreslagen åtgärd och godkänd exekvering.
- Spara reviewer-feedback som data för framtida förbättring.
- Kör verktyg med minsta möjliga behörighet och ett explicit tillåtelselager.

Varning:

- Den granskade gateway-koden har fail-open-liknande beteende när allowlist
  saknas eller har löpt ut. Det mönstret ska inte kopieras.

Konsekvens för projektet:

- Saknad, ogiltig eller utgången policy ska vara fail-closed.
- Första OpenAI-baselinen har noll verktygsanrop.
- Senare verktyg måste ha budget, scope, audit trail och separat approval.

### Rootly AI Labs

Källor:

- [Rootly AI Labs](https://github.com/rootly-ai-labs)
- [Logs Dataset](https://github.com/Rootly-AI-Labs/logs-dataset)
- [Graphify Importer](https://github.com/Rootly-AI-Labs/rootly-graphify-importer)
- [Graph clustering implementation](https://github.com/Rootly-AI-Labs/rootly-graphify-importer/blob/07eed6a54aa9da26dc2a39cbb0171a909213887c/graphify/cluster.py#L23-L84)
- [SRE Skills Bench](https://github.com/Rootly-AI-Labs/sre-skills-bench)

Användbara idéer:

- Apache- och OpenSSH-loggarna är bra för parserrobusthet, mönstergruppering
  och samplingstester.
- Graphify visar värdet av en typad graf och explicita relationer mellan
  resurser.
- SRE Skills Bench visar hur scenario, förväntat beteende och score kan lagras
  som reproducerbara testfall.

Varningar:

- Logs Dataset saknar incidentnivåns root-cause-sanning och räcker därför inte
  för RCA-accuracy.
- README-uppgifter om antal fel är internt inkonsekventa (531 respektive
  19 524 i samma datamaterial). Härled alltid egna counts från rådata.
- En grafkant som observerats, härletts deterministiskt eller föreslagits av
  en modell får inte väga lika.
- Granskad graph-kod använder förenklade/oviktade relationer och fångar vissa
  fel utan tydlig propagation; kopiera inte beteendet direkt.

Konsekvens för projektet:

- Lägg senare till separata adapters för Apache och OpenSSH.
- Använd dem för parser/sampling, inte som facit för root cause.
- Inför edge-proveniens: `observed`, `deterministic_derived`,
  `model_inferred`.

### Awesome AI SRE

Källa:

- [pavangudiwada/awesome-ai-sre](https://github.com/pavangudiwada/awesome-ai-sre)
- [HolmesGPT](https://github.com/HolmesGPT/holmesgpt)
- [K8sGPT](https://github.com/k8sgpt-ai/k8sgpt)
- [kagent](https://github.com/kagent-dev/kagent)
- [SREGym](https://github.com/SREGym/SREGym)

Användbara idéer:

- Listan är bra för att hitta jämförelseprojekt och evalramverk.
- HolmesGPT, K8sGPT och kagent är relevanta för verktygs- och
  Kubernetesmönster.
- SREGym är relevant när vi vill gå från statiska loggar till interaktiva,
  reproducerbara incidentuppgifter.

Begränsning:

En “awesome list” är en katalog, inte evidens för kvalitet. Varje utvalt
projekt måste granskas och benchmarkas separat innan något mönster kopieras.

### Synoeticos

Källor:

- [Feirbrand/synoeticos-public](https://github.com/Feirbrand/synoeticos-public)
- [Exempel med fasta utfall](https://github.com/Feirbrand/synoeticos-public/blob/26e6153a0b3f72fc4817ccd7a575bffb8cdcf4c1/vgs-loadout/frameworks/phoenix-protocol/phoenix_protocol.py#L83-L214)

Användbar konceptuell ordning:

```text
contain → audit → rebuild → validate
```

Varningar:

- Granskade exempel returnerar fasta/simulerade utfall och är inte evidens
  för en fungerande incidentpipeline.
- Licensen är icke-kommersiell.

Konsekvens för projektet:

- Använd endast den konceptuella fasindelningen som inspiration.
- Importera varken kod, påstådda metrics eller implementation.

## Prioriterad backlog efter godkänd OpenAI-baseline

## Review-UX att ta från jämförelseprojekten

InvGate, PagerDuty, AWS, IncidentFox och Akmatori pekar tillsammans mot samma
reviewmönster:

- visa incident-/analysstatus och påverkan före en lång AI-text;
- visa observation, evidens-ID och tidslinje tillsammans;
- skilj modellens hypotes från verifierat faktum;
- gör abstention till ett normalt och tydligt reviewutfall;
- visa `missing evidence` och nästa minsta verifiering;
- lägg rå JSON, verktygsspår och full evidenspack bakom expanderbara detaljer;
- håll analys, reviewer-beslut och exekvering som separata steg;
- tillåt inte approval när analysen är otillgänglig eller inkonklusiv;
- samla rejection-feedback som exakta data-/evidensproblem, inte bara
  “fel svar”.

Detta har nu applicerats på den lokala Hadoop/OpenAI-rapporten:
`output/incident-review.html`. Den visar dataset-facit tydligt som
post-response evaldata, separat från vad modellen faktiskt såg.

### P0 – mät datan före mer AI

| Kandidat | Varför | Acceptanskriterium | Status |
|---|---|---|---|
| Stage-by-stage scorecard | Lokaliserar första signalförlusten | Parser, sampling, gruppering, tidslinje och evidenspack har egna mätvärden | Klar |
| Sampling-scorecard | Visar om tunningen är korrekt | Signal retention, temporal coverage, pattern diversity och evidence recovery rapporteras per case | Klar |
| Evidenspack-kontrakt | Stoppar motsägelser före LLM | “Tillräcklig evidens” kan inte samexistera med noll kandidater; alla claims har kända ID:n | Klar |
| Fyra korrelationslager | Skiljer samtidighet från orsak | Temporal, entity/service, topology/dependency och change/deploy mäts separat | Klar |
| Edge-proveniens | Hindrar inferens från att bli fakta | Varje grafkant har typ, källa, metod, confidence och supporting IDs | Klar |

### P1 – bredare testdata

| Kandidat | Syfte | Acceptanskriterium | Status |
|---|---|---|---|
| Rootly Apache-adapter | Parser- och samplingvariation | Reproducerbar ingest med lokalt härledda counts | Väntar |
| Rootly OpenSSH-adapter | Annan loggstruktur och säkerhetssignal | Samma kontrakt som Hadoop utan specialfall i kärnpipelinen | Väntar |
| HDFS_v1-adapter | Stor blocksekvens-corpus | Full count, label-isolering och balanserat sampling-scorecard | Klar |
| OpenStack-adapter | Rå parser + VM-gruppering | ID-minimering, full parseraccounting och ärlig anomaly coverage | Klar |
| Scenario/fault injection | Kontrollerad kausal sanning | Hadoop-facit används nu som applikationslabel; ett senare eget scenario behöver dessutom onset, affected entity, observerade samtidiga fel, job outcome och expected evidence | Delvis |
| SREGym-spike | Agentisk eval senare | Separat experiment; påverkar inte kärnpipelinen före godkänd spike | Väntar |

### P2 – review och lärande

Det här ligger efter pre-review-pipelinen:

- reviewer-beslut kopplat till exakt prompt-, modell-, kod- och dataversion;
- feedback som separerar fel data, fel korrelation och fel tolkning;
- liknande tidigare incidenter som förslag, aldrig som facit;
- runbook-rekommendationer med ägare och verifieringssteg;
- kalibrering av confidence mot faktiskt review-utfall.

### P3 – åtgärder och drift

Det här ligger sist:

- remediation som proposal/dry-run före exekvering;
- explicit approval, scope, timeout, rollback-plan och audit trail;
- fail-closed tool-policy;
- Railway-deployment, secret management, persistens, monitoring och
  rollback först när lokala eval gates passerar.

### Parkerad men aktiv att-göra-lista

De här idéerna är medvetet senarelagda, inte bortvalda:

- [ ] postmortem-finputsning från en godkänd typad evidensrevision;
- [ ] historiskt review-minne med proveniens och rättningsflöde;
- [ ] remediation/runbook som read-only eller dry-run;
- [ ] rollback endast efter separat approval och verifierad rollback-plan;
- [ ] Rootly Apache/OpenSSH som ytterligare parser-corpora;
- [ ] SREGym som isolerat experiment efter egen fault injection.

## Saker vi uttryckligen inte ska göra

- Ingen fast procentsats som 70/20/10 utan mätdata.
- Ingen “traffic spike”, “upstream degradation” eller systemisk root cause
  utan citerad evidens.
- Ingen automatisk rollback, restart, load-mirroring eller destruktiv åtgärd
  utan verifierat underlag och approval.
- Ingen hård global error-count-gräns.
- Ingen slutsats att “A hände före B” betyder att A orsakade B.
- Ingen modellträning på testetiketterna och ingen sanning i prompten.
- Ingen kvalitetsbedömning enbart från ett snyggt postmortem.

## Gate för att skapa implementationsplanen

Efter det första blindade testet skapas
`IMPLEMENTATION_PLAN_FROM_LINK_FINDINGS.md` endast om:

- alla API-anrop lyckas eller har tydligt klassificerade providerfel;
- 100 % av lyckade svar följer schemat;
- 100 % av citerade evidens-ID:n finns i respektive evidenspack;
- sanningsetiketten aldrig skickas till modellen;
- abstention redovisas separat från felklassificering;
- rapporten innehåller tokenanvändning, latens, modell och promptversion;
- inga kritiska läckage- eller kontraktsfel upptäcks.

Klassificeringsaccuracy är en separat diagnostisk gate. Om transport och
grounding fungerar men modellen inte kan skilja felklasserna ska nästa plan
förbättra parser/sampling/evidenspack — inte maskera problemet med en friare
prompt.

Kontraktsgaten passerade 2026-07-28. Den resulterande planen finns i
`IMPLEMENTATION_PLAN_FROM_LINK_FINDINGS.md` och är därför data-first.

## Ny datasetfinding: labels är inte samma sak som synlig evidens

HDFS_v1 och OpenStack bekräftar att datasetetiketter måste hållas utanför
pipelinen och joinas först vid scoring:

- HDFS_v1 gav 575 061 spår och en stor, stabil parser-/samplingkontroll, men
  endast binär anomaly-sanning—inte root cause;
- OpenStack gav 207 820 primära råevents och fyra märkta anomaliinstanser;
- alla fyra OpenStack-instanser hittades, men ingen hade en direkt
  katalogiserad felsignal i sina 25 INFO-events;
- det korrekta modellbeteendet för dessa fyra är därför abstention eller en
  exakt begäran om mer data;
- den första OpenStack-körningen avslöjade att `warning` inte behandlades som
  `warn` i high-signal-reservationen. Efter fixen ökade distinkt
  högsignal-retention till 100 procent i samtliga filer.

Det här är ett konkret exempel på varför en vacker reviewtext inte är
kvalitetsbevis. Rapporten måste visa vad som fanns i rådata, vad som överlevde
tunningen och vad som saknades.
