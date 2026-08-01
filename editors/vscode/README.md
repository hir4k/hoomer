# Hoomer Language for VS Code

This extension provides syntax highlighting and basic editing support for
Hoomer (`.hmr`) files. Its TextMate scopes follow VS Code's built-in Ruby
grammar, so Hoomer uses the same color language as Ruby in the active theme.

## Install a packaged extension

From the Hoomer repository root:

```sh
code --install-extension editors/vscode/hoomer-language-0.2.0.vsix
```

Reload VS Code after installation. Files ending in `.hmr` will then be detected
as Hoomer automatically.

## Try the extension while developing it

Open `editors/vscode` as a folder in VS Code and press `F5`. In the Extension
Development Host window, open one of the `.hmr` files from Hoomer's `examples`
directory.

Use **Developer: Inspect Editor Tokens and Scopes** from the Command Palette to
inspect the TextMate scope assigned to any token.
