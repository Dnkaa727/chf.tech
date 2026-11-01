{
  description = "chf.tech frontend and local AI model development environment";

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
          ps.httpx2
          ps.pytest
        ]);

        frontend = pkgs.writeShellApplication {
          name = "chf-frontend";
          runtimeInputs = [ pkgs.nodejs ];
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
            export LLM_PIPELINE_MODE="two_stage"
            export LLM_JSON_MODE="schema"
            export LLM_MESSAGE_MODE="system_user"

            cd "$PWD/model" || exit 1
            exec python run.py serve
          '';
        };

      in
      {
        packages = {
          model = model;
          frontend = frontend;
          default = model;
        };

        apps = {
          model = {
            type = "app";
            program = "${model}/bin/chf-model";
          };

          frontend = {
            type = "app";
            program = "${frontend}/bin/chf-frontend";
          };

          default = {
            type = "app";
            program = "${model}/bin/chf-model";
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
            export LLM_PIPELINE_MODE="two_stage"
            export LLM_JSON_MODE="schema"
            export LLM_MESSAGE_MODE="system_user"

          '';
        };
      }
    );
}
