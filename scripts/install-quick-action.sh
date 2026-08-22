#!/bin/zsh
set -eu

script_dir=${0:A:h}
project_dir=${script_dir:h}
source_workflow="$project_dir/quick-action/SelectedTextToSpeech.workflow"
destination="$HOME/Library/Services/SelectedTextToSpeech.workflow"

mkdir -p "$HOME/Library/Services"
if [[ -e "$destination" ]]; then
  /bin/rm -R "$destination"
fi
/usr/bin/ditto "$source_workflow" "$destination"
/usr/bin/plutil -lint "$destination/Contents/Info.plist" "$destination/Contents/document.wflow"
/System/Library/CoreServices/pbs -flush
/System/Library/CoreServices/pbs -update

print "Installed Speak Selection with Local TTS."
print "See start-service-instructions.md to configure and use it."
