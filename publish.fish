set version (sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml)
git commit -am "new v$version"
git tag -a v$version -m "v$version"
git push origin v$version
uv build
uv publish --username __token__ --password (rbw get "pypi" "00sapo" -f "token")
