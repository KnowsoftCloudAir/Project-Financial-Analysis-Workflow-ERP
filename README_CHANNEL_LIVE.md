# Channel dock: current live → else latest video

```
https://www.youtube.com/channel/UCEXGDNclvmg6RW0vipJYsTQ/live
```

1. **Live now** → docks that live broadcast video  
2. **Not live** → docks the **latest available** video on the channel  
3. Cached ~2 minutes  

Single video links (`watch?v=…`) still play only that video.

## Install
1. Replace `app/routers/social_stream.py`
2. Keep `templates/members/social_watch.html` from this pack
3. Redeploy, open Social Watch (embed is resolved fresh on each page load)
