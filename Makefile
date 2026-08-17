build:
	python3 build.py

serve: build
	cd public && python3 -m http.server 8321

.PHONY: build serve
