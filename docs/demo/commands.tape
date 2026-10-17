# Real commands on the Just a Dev channel.
Output out/commands.mp4
Source common.tape
Set Width 1280
Set Height 860
Set TypingSpeed 18ms

Hide
Type "source shell.sh commands"
Enter
Sleep 1s
Show

Sleep 200ms
Type "ytk channel get @justadevshow | jq '{title, subscribers: .stats.subscribers, videos: .stats.videos}'"
Sleep 300ms
Enter
Wait /^~ \$$/
Sleep 1.5s
Type "ytk analytics --by video --limit 3 | jq -r '.rows[].video' | xargs ytk video get | jq -r '.[].title'"
Sleep 300ms
Enter
Wait /^~ \$$/
Sleep 1.8s
Type "ytk analytics --by traffic-source --since 28d --metrics views | jq -c '.rows[]'"
Sleep 300ms
Enter
Wait /^~ \$$/
Sleep 3s
