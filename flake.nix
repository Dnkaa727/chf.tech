{
  description = "chf.tech frontend, backend and local AI model environment";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs";
    utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      utils,
    }:
    utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };

        python = pkgs.python3.withPackages (ps: [
          ps.fastapi
          ps.uvicorn
          ps.websockets
          ps.httpx2
          ps.pytest
        ]);

        frontend = pkgs.writeShellApplication {
          name = "chf-frontend";

          runtimeInputs = [
            pkgs.nodejs
          ];

          text = ''
            cd "$PWD" || exit 1

            if [ ! -d frontend/node_modules ]; then
              npm --prefix frontend ci
            fi

            exec npm --prefix frontend run dev -- --host 127.0.0.1
          '';
        };

        model = pkgs.writeShellApplication {
          name = "chf-model";

          runtimeInputs = [ python ];

          text = ''
            export LLM_BASE_URL="https://api.hubris.pw/v1"
            export LLM_MODEL="openai/gpt-4o-mini"
            export LLM_TIMEOUT_SECONDS="75"
            export LLM_PIPELINE_MODE="one_stage"
            export LLM_JSON_MODE="schema"
            export LLM_MESSAGE_MODE="system_user"

            cd "$PWD/model" || exit 1
            exec python run.py serve
          '';
        };

        backend = pkgs.writeShellApplication {
          name = "chf-backend";

          runtimeInputs = [ python ];

          text = ''
            export LLM_BASE_URL="https://api.hubris.pw/v1"
            export LLM_MODEL="openai/gpt-4o-mini"
            export LLM_TIMEOUT_SECONDS="75"
            export LLM_PIPELINE_MODE="one_stage"
            export LLM_JSON_MODE="schema"
            export LLM_MESSAGE_MODE="system_user"

            export BACKEND_HOST="127.0.0.1"
            export BACKEND_PORT="8081"
            export FRONTEND_ORIGINS="http://127.0.0.1:5173,http://localhost:5173"

            cd "$PWD" || exit 1
            exec uvicorn backend.main:app \
              --host "$BACKEND_HOST" \
              --port "$BACKEND_PORT"
          '';
        };

        all = pkgs.writeShellApplication {
          name = "chf-all";

          runtimeInputs = [
            backend
            frontend
            pkgs.coreutils
          ];

          text = ''
            cd "$PWD" || exit 1

            chf-backend &
            backend_pid=$!

            cleanup() {
              kill "$backend_pid" 2>/dev/null || true
            }

            trap cleanup EXIT INT TERM

            chf-frontend
          '';
        };
      in
      {
        packages = {
          model = model;
          backend = backend;
          frontend = frontend;
          all = all;
          default = all;
        };

        apps = {
          model = {
            type = "app";
            program = "${model}/bin/chf-model";
          };

          backend = {
            type = "app";
            program = "${backend}/bin/chf-backend";
          };

          frontend = {
            type = "app";
            program = "${frontend}/bin/chf-frontend";
          };

          all = {
            type = "app";
            program = "${all}/bin/chf-all";
          };

          default = {
            type = "app";
            program = "${all}/bin/chf-all";
          };
        };

        devShells.default = pkgs.mkShell {
          name = "chf.tech";

          packages = [
            python
            pkgs.nodejs
            pkgs.git
          ];

          shellHook = ''
            export LLM_BASE_URL="https://api.hubris.pw/v1"
            export LLM_MODEL="openai/gpt-4o-mini"
            export LLM_TIMEOUT_SECONDS="75"
            export LLM_PIPELINE_MODE="one_stage"
            export LLM_JSON_MODE="schema"
            export LLM_MESSAGE_MODE="system_user"
            export BACKEND_HOST="127.0.0.1"
            export BACKEND_PORT="8081"
          '';
        };
      }
    );
}
