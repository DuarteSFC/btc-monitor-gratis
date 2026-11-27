"""Export verified completed 5m spot bars for unchanged production-rule benchmark."""
import argparse,tempfile
from pathlib import Path
from market_frame import load_minutes,bars
from validation_rehearsal import scoped_spot
from extension_2026 import scope_2026
def main():
    p=argparse.ArgumentParser();p.add_argument("--dataset",required=True);a=p.parse_args()
    for name,scope in [("2022-23",scoped_spot),("2026",scope_2026)]:
        with tempfile.TemporaryDirectory() as tmp:
            scope(a.dataset,tmp);d=load_minutes(tmp)
        b=bars(d,5)
        b.insert(0,"t",b.index.as_unit("ns").asi8//1000000-300000)
        b[["t","open","high","low","close","volume","segment"]].to_csv("lab-b07-"+name+".csv",index=False)
        print("B07_SOURCE",name,len(b),flush=True)
if __name__=="__main__":main()
