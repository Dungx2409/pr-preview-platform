{{/*
Expand the name of the chart.
*/}}
{{- define "app.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "app.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create a default fully qualified postgres name.
*/}}
{{- define "app.postgresFullname" -}}
{{- printf "%s-postgres" (include "app.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Generate a deterministic per-release postgres password when none is provided.
Deriving from the release name keeps it stable across Argo CD re-syncs (no
password churn) while avoiding a shared hardcoded default.
*/}}
{{- define "app.postgresPassword" -}}
{{- .Values.postgres.password | default (printf "%s" .Release.Name | sha256sum | trunc 16) -}}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "app.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "app.labels" -}}
helm.sh/chart: {{ include "app.chart" . }}
{{ include "app.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Values.pr.number }}
pr: {{ .Values.pr.number | quote }}
{{ (get (.Values.repo | default dict) "label") | default "preview" }}: "true"
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "app.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "app.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Normalized services list for multi-service or single-service (monolith) workloads.
Produces a list of service maps, each normalized to:
  name, image, port, healthcheck, buildDir, path.
When .Values.services is non-empty, iterates over .Values.services and applies defaults.
When .Values.services is absent/empty, derives one service from the legacy app block
for full backward compatibility.
*/}}
{{- define "app.services" -}}
{{- $services := list -}}
{{- if and .Values.services (gt (len .Values.services) 0) -}}
  {{- range .Values.services -}}
    {{- $name := .name -}}
    {{- $image := .image -}}
    {{- $port := (.port | default 8000) | int -}}
    {{- $healthcheck := .healthcheck | default "/healthz" -}}
    {{- $buildDir := .buildDir | default $name -}}
    {{- $path := .path | default "/" -}}
    {{- $svc := dict "name" $name "image" $image "port" $port "healthcheck" $healthcheck "buildDir" $buildDir "path" $path -}}
    {{- $services = append $services $svc -}}
  {{- end -}}
{{- else -}}
  {{- $app := .Values.app | default dict -}}
  {{- $appName := (get $app "name") | default "demo-app" -}}
  {{- $appImage := (get $app "image") | default (get (.Values.image | default dict) "repository") | default "ghcr.io/dungx2409/demo-app" -}}
  {{- $appPort := (get $app "port") | default (get (.Values.service | default dict) "targetPort") | default 8000 | int -}}
  {{- $appHealthcheck := (get $app "healthcheck") | default "/healthz" -}}
  {{- $appBuildDir := (get $app "buildDir") | default $appName -}}
  {{- $appPath := (get $app "path") | default "/" -}}
  {{- $svc := dict "name" $appName "image" $appImage "port" $appPort "healthcheck" $appHealthcheck "buildDir" $appBuildDir "path" $appPath -}}
  {{- $services = append $services $svc -}}
{{- end -}}
{{- toYaml $services -}}
{{- end }}

{{/*
Create a default fully qualified service name.
Accepts either:
  - dict with "root" (or "context") and "service" (service map or name string) or "name"
  - list with [root, service_map_or_name]
  - root context alone (falls back to app.fullname)
When .Values.services is absent/empty, returns app.fullname for backward compatibility.
When .Values.services is present, appends the service name to app.fullname.
*/}}
{{- define "app.serviceFullname" -}}
{{- $root := . -}}
{{- $svcName := "" -}}
{{- if kindIs "slice" . -}}
  {{- $root = index . 0 -}}
  {{- $s := index . 1 -}}
  {{- if kindIs "map" $s -}}
    {{- $svcName = $s.name -}}
  {{- else -}}
    {{- $svcName = printf "%s" $s -}}
  {{- end -}}
{{- else if kindIs "map" . -}}
  {{- if hasKey . "root" -}}
    {{- $root = .root -}}
  {{- else if hasKey . "context" -}}
    {{- $root = .context -}}
  {{- end -}}
  {{- if hasKey . "service" -}}
    {{- if kindIs "map" .service -}}
      {{- $svcName = .service.name -}}
    {{- else -}}
      {{- $svcName = printf "%s" .service -}}
    {{- end -}}
  {{- else if hasKey . "name" -}}
    {{- $svcName = .name -}}
  {{- else if hasKey . "serviceName" -}}
    {{- $svcName = .serviceName -}}
  {{- end -}}
{{- end -}}
{{- $base := include "app.fullname" $root -}}
{{- if not (and $root.Values.services (gt (len $root.Values.services) 0)) -}}
  {{- $base -}}
{{- else if or (not $svcName) (eq $svcName "app") -}}
  {{- $base -}}
{{- else -}}
  {{- printf "%s-%s" $base $svcName | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end }}

{{/*
Per-service selector labels.
When .Values.services is absent/empty, keeps component: app for backward compatibility.
When .Values.services is present, sets component: <service.name>.
*/}}
{{- define "app.serviceSelectorLabels" -}}
{{- $root := . -}}
{{- $svcName := "" -}}
{{- if kindIs "slice" . -}}
  {{- $root = index . 0 -}}
  {{- $s := index . 1 -}}
  {{- if kindIs "map" $s -}}
    {{- $svcName = $s.name -}}
  {{- else -}}
    {{- $svcName = printf "%s" $s -}}
  {{- end -}}
{{- else if kindIs "map" . -}}
  {{- if hasKey . "root" -}}
    {{- $root = .root -}}
  {{- else if hasKey . "context" -}}
    {{- $root = .context -}}
  {{- end -}}
  {{- if hasKey . "service" -}}
    {{- if kindIs "map" .service -}}
      {{- $svcName = .service.name -}}
    {{- else -}}
      {{- $svcName = printf "%s" .service -}}
    {{- end -}}
  {{- else if hasKey . "name" -}}
    {{- $svcName = .name -}}
  {{- else if hasKey . "serviceName" -}}
    {{- $svcName = .serviceName -}}
  {{- end -}}
{{- end -}}
{{ include "app.selectorLabels" $root }}
{{- if and $root.Values.services (gt (len $root.Values.services) 0) }}
app.kubernetes.io/component: {{ $svcName }}
{{- else }}
app.kubernetes.io/component: app
{{- end }}
{{- end }}

{{/*
Per-service common labels.
*/}}
{{- define "app.serviceLabels" -}}
{{- $root := . -}}
{{- $svcName := "" -}}
{{- if kindIs "slice" . -}}
  {{- $root = index . 0 -}}
  {{- $s := index . 1 -}}
  {{- if kindIs "map" $s -}}
    {{- $svcName = $s.name -}}
  {{- else -}}
    {{- $svcName = printf "%s" $s -}}
  {{- end -}}
{{- else if kindIs "map" . -}}
  {{- if hasKey . "root" -}}
    {{- $root = .root -}}
  {{- else if hasKey . "context" -}}
    {{- $root = .context -}}
  {{- end -}}
  {{- if hasKey . "service" -}}
    {{- if kindIs "map" .service -}}
      {{- $svcName = .service.name -}}
    {{- else -}}
      {{- $svcName = printf "%s" .service -}}
    {{- end -}}
  {{- else if hasKey . "name" -}}
    {{- $svcName = .name -}}
  {{- else if hasKey . "serviceName" -}}
    {{- $svcName = .serviceName -}}
  {{- end -}}
{{- end -}}
{{ include "app.labels" $root }}
{{- if and $root.Values.services (gt (len $root.Values.services) 0) }}
app.kubernetes.io/component: {{ $svcName }}
{{- else }}
app.kubernetes.io/component: app
{{- end }}
{{- end }}
