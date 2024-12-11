
# Welcome!
Here is where I want to make data analysis available to DJs.
Many of these notebooks are on google Colab so you can run the notebooks on your own data. You'll have to click through some agreements if it's your first time. 

Start with the app!
[![Playlists and DJs](https://github.com/ThomasMAhern/WCS_playlist_analysis/blob/main/graphs/DJ%20playlist%20app.jpg)](https://west-coast-swing-dj-playlist-analysis.streamlit.app/)

You can also view the [Jupyter Notebook](https://github.com/ThomasMAhern/WCS_playlist_analysis/blob/main/notebooks/WCS_playlist_analysis.ipynb) of BPM graphs of assorted playlists - you can't interact with this one unless you download the .ipynb file and run it yourself.

Please reach out if you need help running the notebooks below. It can be confusing to look at at first, but it's well worth the hassle!

## If you want to see the BPM graphs on your own playlist(s), try this notebook:
Not as pretty and polished yet, but it'll get there.
[Playlist BPM Grapher](https://colab.research.google.com/drive/11E7wQ6Ccf2CFu5vbWURZbT3i7vYaNZJJ?usp=sharing)!
![BPM Grapher](https://github.com/ThomasMAhern/WCS_playlist_analysis/blob/main/graphs/BPM_graphs.jpg)



## Data Sources:

Most of the data is from Spotify, I followed Westie DJ's and scraped their playlists using the Spotify API. I re-scrape every once in a while once I follow more people (the last time the playlist file was updated is a good indicator of recency).

I downloaded [Koichi's sets in Tableau](https://public.tableau.com/app/profile/koichi.tsunoda3069/viz/DJStats/Sets) cleaned it up a bit to suit my schema, and then incorporated it.

[Connie](https://conniedoesdata.com/2023/03/29/WCS-DJ-Spreadsheet/) was also kind enough to give me a copy of her data/spreadsheet. I manually combined each sheet's data with the corresponding names and did some additional tweaking to fit my needs.

I manually scraped the [Pro Swing DJ's](https://proswingdjs.com/) song lists and tweaked them to suit my format (and followed their linked DJ's so they'd be caught by my next Spotify pull - though I'd already had most of them).


