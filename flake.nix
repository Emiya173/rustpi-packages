{
  description = "Tools for maintaining the signed Emiya rustpi pacman repository";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/a033e66ab94a6bedf2c3d58d93a36319d3cbbbaf";
  outputs = { nixpkgs, ... }: {
    devShells.x86_64-linux.default = let
      pkgs = import nixpkgs { system = "x86_64-linux"; };
    in pkgs.mkShell {
      packages = with pkgs; [ python3 git gh gnupg pacman libarchive fakeroot zstd xz curl shellcheck actionlint ];
    };
  };
}
