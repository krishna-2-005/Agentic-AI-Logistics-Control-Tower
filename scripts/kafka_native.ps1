# G-05 without Docker — a real Kafka broker run natively on the JVM (Windows).
#
#   powershell -ExecutionPolicy Bypass -File scripts\kafka_native.ps1 -Setup   # once: download + format
#   powershell -ExecutionPolicy Bypass -File scripts\kafka_native.ps1          # start the broker
#
# Then, from the repo root in another terminal:
#   $env:PYSPARK_SUBMIT_ARGS = "--packages org.apache.spark:spark-sql-kafka-0-10_2.13:4.0.4 pyspark-shell"
#   python -m src.streaming.job --kafka --duration 240 --clean --stats-out benchmarks/raw/w7_kafka_live.json
#   python -m src.streaming.producer --sink kafka --limit 2000 --duration 60 --validate
#   python -m src.streaming.compare_sources
#
# Why this exists alongside docker-compose.kafka.yml: G-05 was blocked for two weeks on
# "no Docker on this machine", but Kafka is a Java program and the machine has had a JDK
# since Week 1. Two Windows-specific traps, both handled below:
#   * kafka-server-start.bat calls `wmic` to size the heap, and Windows 11 no longer ships
#     wmic. Setting KAFKA_HEAP_OPTS first skips that branch entirely.
#   * the default log.dirs is a /tmp path; it is pointed at a real Windows directory.

param(
    [switch]$Setup,
    [string]$KafkaVersion = "4.1.2",
    [string]$Root = "D:\kafka",
    [string]$JavaHome = $env:JAVA_HOME
)

$ErrorActionPreference = "Stop"
if (-not $JavaHome) { throw "Set JAVA_HOME to a JDK 17+ (or pass -JavaHome)." }
$env:JAVA_HOME = $JavaHome
$env:Path = "$JavaHome\bin;$env:Path"
$env:KAFKA_HEAP_OPTS = "-Xmx1G -Xms512M"   # skips the wmic probe in kafka-server-start.bat

$home_ = Join-Path $Root "kafka_2.13-$KafkaVersion"
$config = Join-Path $home_ "config\server.properties"

if ($Setup) {
    New-Item -ItemType Directory -Force $Root | Out-Null
    $tgz = Join-Path $Root "kafka.tgz"
    # The Apache CDN; archive.apache.org is too slow to finish inside a timeout.
    Invoke-WebRequest "https://dlcdn.apache.org/kafka/$KafkaVersion/kafka_2.13-$KafkaVersion.tgz" -OutFile $tgz
    tar -xzf $tgz -C $Root
    Remove-Item $tgz
    $data = (Join-Path $Root "data") -replace '\\', '/'
    (Get-Content $config) -replace '^log\.dirs=.*', "log.dirs=$data" | Set-Content $config -Encoding ascii
    $id = (& "$home_\bin\windows\kafka-storage.bat" random-uuid).Trim()
    & "$home_\bin\windows\kafka-storage.bat" format -t $id -c $config --standalone
    Write-Host "formatted cluster $id; run this script again without -Setup to start the broker"
    exit 0
}

& "$home_\bin\windows\kafka-server-start.bat" $config
