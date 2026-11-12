"""Conservative FTB Quests chapter draft writer; validate in-game for target version."""
import json, secrets, re
ITEM_RE=re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")
def uid(): return secrets.token_hex(8).upper()
def snbt_string(v): return json.dumps(str(v),ensure_ascii=False)
def _item(v,fallback): return v if isinstance(v,str) and ITEM_RE.fullmatch(v) else fallback
def _count(v):
    try: return max(1,min(64,int(v)))
    except (TypeError,ValueError): return 1
def validate_campaign(data):
    if not isinstance(data,dict) or not isinstance(data.get("chapters"),list) or len(data["chapters"])!=3:
        raise ValueError("Quest plan must contain exactly three chapters.")
    for ci,ch in enumerate(data["chapters"],1):
        if not isinstance(ch,dict) or not isinstance(ch.get("quests"),list) or not ch["quests"]: raise ValueError(f"Chapter {ci} needs quests.")
        ch["quests"]=ch["quests"][:8]
        for qi,q in enumerate(ch["quests"],1):
            if not isinstance(q,dict) or not isinstance(q.get("tasks"),list) or not q["tasks"]: raise ValueError(f"Chapter {ci}, quest {qi} needs an item task.")
            q["tasks"]=[t for t in q["tasks"] if isinstance(t,dict)][:4]
            if not q["tasks"]: raise ValueError(f"Chapter {ci}, quest {qi} has no valid tasks.")
            if not isinstance(q.get("reward"),dict): q["reward"]={"item":"minecraft:bread","count":1}
    return data
def build_chapter(ch,index):
    lines=["{",f'  id: "{uid()}"',f'  title: {snbt_string(ch.get("title",f"Chapter {index}"))}',
        f'  description: {snbt_string(ch.get("description",""))}',"  quests: ["]
    for n,q in enumerate(ch.get("quests",[])[:8]):
        lines += ["    {",f'      id: "{uid()}"',f"      x: {float(n*2):.1f}d","      y: 0.0d",
            f'      title: {snbt_string(q.get("title","New Quest"))}',f'      description: {snbt_string(q.get("description",""))}',"      tasks: ["]
        for t in q.get("tasks",[])[:4]:
            lines += ["        {",f'          id: "{uid()}"','          type: "item"',
                f'          item: {snbt_string(_item(t.get("item"),"minecraft:book"))}',f'          count: {_count(t.get("count"))}L',"        }"]
        reward=q.get("reward") or {}
        lines += ["      ]","      rewards: [","        {",f'          id: "{uid()}"','          type: "item"',
            f'          item: {snbt_string(_item(reward.get("item"),"minecraft:bread"))}',f'          count: {_count(reward.get("count"))}L',
            "        }","      ]","    }"]
    lines += ["  ]","}"]; return "\n".join(lines)+"\n"
