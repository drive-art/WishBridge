import json,os
FILE=os.path.expanduser("~/WishBridge/memory.json")

def load():
    if not os.path.exists(FILE):
        return []
    return json.load(open(FILE))

def save(d):
    json.dump(d,open(FILE,"w"),indent=2)

def remember(text):
    m=load()
    m.append(text)
    if len(m)>3:
        m=m[-3:]
    save(m)

if __name__=="__main__":
    print(load())
