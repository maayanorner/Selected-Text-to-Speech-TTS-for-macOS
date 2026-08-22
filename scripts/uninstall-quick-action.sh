#!/bin/zsh
set -eu

destination="$HOME/Library/Services/SelectedTextToSpeech.workflow"

if [[ -e "$destination" ]]; then
  /bin/rm -R "$destination"
  /System/Library/CoreServices/pbs -flush
  /System/Library/CoreServices/pbs -update
  print "Removed Speak Selection with Local TTS."
else
  print "Speak Selection with Local TTS is not installed."
fi
