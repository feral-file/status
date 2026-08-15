build:
	python3 build.py
	python3 tools/check_claims.py

serve: build
	cd public && python3 -m http.server 8321

.PHONY: build serve
