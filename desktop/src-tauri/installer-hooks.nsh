!macro NSIS_HOOK_POSTINSTALL
  CreateShortcut "$DESKTOP\Video Mix Pro.lnk" "$INSTDIR\Video Mix Pro.exe"
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$DESKTOP\Video Mix Pro.lnk"
!macroend
