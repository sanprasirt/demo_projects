#!/bin/sh
# Create read and write personal access tokens on GitLab CE, then seed the demo project.
# The CE container must already be healthy. This is not used by the mock profile.
set -eu
cd "$(dirname "$0")/.."
docker compose --profile gitlab exec -T gitlab gitlab-rails runner '
user = User.find_by_username("root")
{
  "sre-read" => ["read_api"],
  "sre-write" => ["api"]
}.each do |name, scopes|
  params = { name: name, scopes: scopes, expires_at: 30.days.from_now }
  result = PersonalAccessTokens::CreateService.new(current_user: user, target_user: user, params: params).execute
  token = result.payload[:personal_access_token]
  puts "#{name} #{token.token}"
end
'
echo "Put sre-read into GITLAB_READ_TOKEN and sre-write into GITLAB_WRITE_TOKEN, then run scripts/seed_gitlab.py"
