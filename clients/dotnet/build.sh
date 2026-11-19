#!/usr/bin/env bash
set -euo pipefail
client_root="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$client_root/../.." && pwd)"
export DOTNET_CLI_HOME="${DOTNET_CLI_HOME:-$repo_root/.cache/dotnet}"
export NUGET_PACKAGES="${NUGET_PACKAGES:-$repo_root/.cache/nuget}"
project="$client_root/EzLLMRouter.Client/EzLLMRouter.Client.csproj"
packages="$client_root/build/packages"
dotnet restore "$project" --configfile "$client_root/NuGet.Config"
dotnet pack "$project" --no-restore --configuration Release --output "$packages"
if [[ "${1:-}" == "test" ]]; then
  tests="$client_root/EzLLMRouter.Client.Tests/EzLLMRouter.Client.Tests.csproj"
  dotnet restore "$tests" --source "$packages" -p:ClientPackageDirectory="$packages"
  dotnet build "$tests" --no-restore --configuration Release -p:ClientPackageDirectory="$packages"
  dotnet "$client_root/EzLLMRouter.Client.Tests/bin/Release/net10.0/EzLLMRouter.Client.Tests.dll" \
    "$repo_root/tests/client_languages/cases.json"
fi
