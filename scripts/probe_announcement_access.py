"""Read-only access probe; records failure, never substitutes cached data."""
import argparse,json,datetime,urllib.request,urllib.error,ssl,socket,pathlib
parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
urls=['https://mid.ru/en/foreign_policy/news/1944697/','https://www.mid.ru/ru/foreign_policy/news/1819686/']
results=[]
for url in urls:
 result={'url':url,'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 try:
  request=urllib.request.Request(url,headers={'User-Agent':'Ammitto RU local access verification','Accept':'text/html'})
  with urllib.request.urlopen(request,timeout=15) as response:
   body=response.read(2_000_001);result.update(status=response.status,content_type=response.headers.get('Content-Type'),bytes=len(body),over_limit=len(body)>2_000_000)
   result['usable_html']=response.status==200 and 'text/html' in response.headers.get('Content-Type','') and not result['over_limit']
 except (OSError,urllib.error.URLError,ssl.SSLError,socket.timeout) as error:
  result.update(usable_html=False,error_type=type(error).__name__,error=str(error))
 results.append(result)
report={'mode':'access_probe_only','results':results,'successful_html_responses':sum(r['usable_html'] for r in results)}
pathlib.Path(args.output).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
