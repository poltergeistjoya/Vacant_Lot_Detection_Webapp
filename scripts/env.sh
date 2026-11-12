# Sourced by deploy.sh and scripts/*.sh (bash or zsh): loads deployment settings
# from .env in the repo root (gitignored; template: .env.example).

_ENV_SH="${BASH_SOURCE[0]:-${(%):-%x}}"
ENV_FILE="${ENV_FILE:-$(cd "$(dirname "$_ENV_SH")/.." && pwd)/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi

# require_env VAR...: exit if any variable is unset or empty
require_env() {
  local missing=0 v
  for v in "$@"; do
    if [[ -z "$(eval "printf %s \"\${$v:-}\"")" ]]; then
      echo "Missing $v: set it in .env (see .env.example)" >&2
      missing=1
    fi
  done
  (( !missing )) || exit 1
}
