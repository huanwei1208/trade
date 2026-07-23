```bash
30 17 * * 1-5  cd /home/peng/PROGRAM/GitHub/trade && ./trade py data kline sync --mode incremental --adjust hfq --provider sina 
30 18 * * 1-5  cd /home/peng/PROGRAM/GitHub/trade && ./trade py data sentiment 
0  19 * * 1-5  cd /home/peng/PROGRAM/GitHub/trade && ./trade py daily belief && ./trade py daily recommend 



```