# Records a séance with the original flask.py as a GIF (https://github.com/charmbracelet/vhs).
# Expects Ollama running and Flask cloned into ./flask, as in the workflow.

Output site/seance.gif

Set Shell bash
Set FontSize 20
Set Width 1280
Set Height 560
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Set PlaybackSpeed 2.5

Type "python3 afterlife.py seance flask.py flask"
Sleep 400ms
Enter
Wait@60s /you ›\s*$/

Type "Who are you, spirit?"
Enter
Wait@240s /you ›\s*$/

Type "Why did they delete you?"
Enter
Wait@240s /you ›\s*$/
Sleep 3s
