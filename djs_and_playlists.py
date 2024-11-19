import streamlit as st
import polars as pl

pl.Config.set_tbl_rows(100).set_fmt_str_lengths(100)

regex_year_first = r'\d{2,4}[.\-/ ]?\d{1,2}[.\-/ ]?\d{1,2}'
regex_year_last = r'\d{1,2}[.\-/ ]?\d{1,2}[.\-/ ]?\d{2,4}'
regex_year_abbreviated = r"'\d{2}"

def wcs_specific(df_):
  '''given a df, filter to the records most likely to be west coast swing related'''
  return (df_.lazy()
          .filter(~(pl.col('playlist_name').str.contains(regex_year_first)
                  |pl.col('playlist_name').str.contains(regex_year_last)
                  |pl.col('playlist_name').str.contains(regex_year_abbreviated)
                  |pl.col('playlist_name').str.to_lowercase().str.contains('wcs|social|party|oirée|west coast|routine|blues|practice|practise|bpm|swing|novice|intermediate|comp|musicality|timing|pro show')))
      )

df = (pl.scan_parquet('wcs_dj_spotify_playlists.parquet')
      .rename({'name':'playlist_name'})
      #makes a new column filled with a date - this is good indicator if there was a set played
      .with_columns(extracted_date = pl.concat_list(pl.col('playlist_name').str.extract_all(regex_year_last),
                                                    pl.col('playlist_name').str.extract_all(regex_year_last),
                                                    pl.col('playlist_name').str.extract_all(regex_year_abbreviated),)
                                       .list.unique().list.sort(),
                    song = pl.concat_str('track.name', pl.lit(' - https://open.spotify.com/track/'), 'track.id', ignore_nulls=True),
                    region = pl.col('location').str.split(' - ').list.get(0),)
      
      #gets the counts of djs, playlists, and geographic regions a song is found in
      .with_columns(dj_count = pl.n_unique('owner.display_name').over(pl.col('song')),
                    playlist_count = pl.n_unique('playlist_name').over(pl.col('song')),
                    regions = pl.col('region').over('song', mapping_strategy='join')
                                  .list.unique()
                                  .list.drop_nulls()
                                  .list.sort()
                                  .list.join(', '),)
      .with_columns(geographic_region_count = pl.when(pl.col('regions').str.len_bytes() != 0)
                                    .then(pl.col('regions').str.split(', ').list.drop_nulls().list.len())
                                    .otherwise(0))
      )







st.markdown("## Westie DJ-playlist Database:")
st.text("Note: this database lacks most of the non-spotify playlists - but if you know a DJ, pass this to them and tell them they should put their playlists on spotify so we can add them to the collection! (a separate playlist by date is easiest for me ;) )\n")
st.write(f"{df.select(pl.concat_str('track.name', pl.lit(' - '), 'track.id')).unique().collect(streaming=True).shape[0]:,} Songs ({df.pipe(wcs_specific).select(pl.concat_str('track.name', pl.lit(' - '), 'track.id')).unique().collect(streaming=True).shape[0]:,} wcs specific)")
st.write(f"{df.select('artist').unique().collect(streaming=True).shape[0]:,} Artists ({df.pipe(wcs_specific).select('artist').unique().collect(streaming=True).shape[0]:,} wcs specific)")
st.write(f"{df.select('playlist_name').unique().collect(streaming=True).shape[0]:,} Playlists ({df.pipe(wcs_specific).select('playlist_name').collect(streaming=True).unique().shape[0]:,} wcs specific)\n\n")




data_view_toggle = st.toggle("See sample of the raw data")

if data_view_toggle:
    st.dataframe(df.collect().sample(100))





#courtesy of Vishal S
song_locator_toggle = st.toggle("Song locator")
if song_locator_toggle:
    song_input = st.text_input("Input song name").lower()
    st.dataframe(df
     .filter(pl.col('song').str.to_lowercase().str.contains(song_input))
     .group_by('song')
     .agg('playlist_name', 'owner.display_name', 'artist')
     .with_columns(pl.col('playlist_name', 'owner.display_name', 'artist').list.unique().list.sort())
     .collect()
    )

#courtesy of Vishal S
playlist_locator_toggle = st.toggle("Playlist locator")
if playlist_locator_toggle:
    playlist_input = st.text_input("Input playlist name").lower()
    dj_input = st.text_input("Input dj name").lower()
    st.dataframe(df
     .filter(pl.col('playlist_name').str.to_lowercase().str.contains(playlist_input),
             pl.col('owner.display_name').str.to_lowercase().str.contains(dj_input))
     .group_by('playlist_name')
     .agg('owner.display_name', pl.n_unique('song').alias('song_count'), pl.n_unique('artist').alias('artist_count'), 'song')
     .with_columns(pl.col('owner.display_name', 'song').list.unique().list.sort(),)
     .collect()
    )







#courtesy of Lino V
search_dj_toggle = st.toggle("Insights about a particular DJ")

if search_dj_toggle:

    st.markdown("#### Enter a Spotify `display_name` or `user_id`:")
    id_input = st.text_input("ex. Kasia Stepek or 1185428002")
    dj_id = id_input.lower().strip()
    
    
    
    st.markdown(f"#### Popular music _{id_input}_ doesn't play")
    dj_music = [i[0] for i in (df
                .filter(pl.col('owner.id').str.contains(dj_id)
                        | pl.col('owner.display_name').str.to_lowercase().str.contains(dj_id))
                .select('track.id')
                .unique()
                .collect()
                .iter_rows()
               )]
    
    not_my_music = (df
                    #  .pipe(wcs_specific)
                    .filter(~pl.col('owner.id').str.contains(dj_id)
                            | ~pl.col('owner.display_name').str.contains(dj_id))
                    .filter(~pl.col('track.id').is_in(dj_music))
                    .filter(pl.col('dj_count') > 5,
                            pl.col('playlist_count') > 5)
                    .select('song', 'dj_count', 'playlist_count', 'regions', 'geographic_region_count')
                    .unique()
                    .sort('playlist_count', descending=True)
                    )
    
    st.dataframe(not_my_music.head(200).collect())
    
    
    
    
    
    








    st.markdown(f"#### Music unique to _{id_input}_")
    only_i_play = (df
                  #  .pipe(wcs_specific)
                  .filter(pl.col('dj_count').eq(1)
                          &(pl.col('owner.id').str.contains(dj_id)
                            |pl.col('owner.display_name').str.to_lowercase().str.contains(dj_id))
                         )
                  .select('song', 'dj_count', 'owner.display_name', 'playlist_count', 'regions', 'geographic_region_count')
                  .unique()
                  .sort('playlist_count', descending=True)
                  )
    
    st.dataframe(only_i_play.head(200).collect(streaming=True))







st.markdown("# ")

#courtesy of Vincent M
songs_together_toggle = st.toggle("Songs most played together")

if songs_together_toggle:
    st.markdown(f"## Most common songs played back-to-back")
    
    st.markdown("#### Enter a partial/full `track.name` or `song_id`:")
    song_input = st.text_input("ex. 'purple' or '0bGH7ezs7WdDwpqnsvGf1z'")
    song_input_prepped = song_input.lower().strip()
    st.markdown(f"#### Most common songs played next to _{song_input}_:")
    st.text("Song name: song_id (to distinguish between song versions)")
    
    st.dataframe(df
     .select('song_number', 'track.name', 'playlist_name', 'track.id', 'playlist_id', 'owner.display_name')
     .unique()
     .sort('playlist_id', 'song_number')
     
     .with_columns(pair1 = pl.when(pl.col('song_number').shift(-1) > pl.col('song_number'))
                            .then(pl.concat_str(pl.col('track.name'), pl.lit(': '), pl.col('track.id'), pl.lit(' --- '),
                                                pl.col('track.name').shift(-1), pl.lit(': '), pl.col('track.id').shift(-1),
                                                )),
                   pair2 = pl.when(pl.col('song_number').shift(1) < pl.col('song_number'))
                            .then(pl.concat_str(pl.col('track.name').shift(-1), pl.lit(': '), pl.col('track.id').shift(1), pl.lit(' --- '),
                                                pl.col('track.name'), pl.lit(': '), pl.col('track.id'),
                                                )),
                  )
     .with_columns(pair = pl.concat_list('pair1', 'pair2'))
     .explode('pair')
     .select('pair', 'playlist_name', 'owner.display_name'
            )
     .drop_nulls()
     .unique()
     .with_columns(pl.col('pair').str.split(' --- ').list.sort().list.join(' --- '))
     .group_by('pair')
     .agg(pl.n_unique('playlist_name').alias('times_played_together'), 'playlist_name', 'owner.display_name',)
     .with_columns(pl.col('playlist_name').list.unique(),
                  pl.col('owner.display_name').list.unique())
     .filter(~pl.col('playlist_name').list.join(', ').str.contains_any(['The Maine', 'delete', 'SPOTIFY']),
            pl.col('times_played_together').gt(1),
            )
     .filter(pl.col('pair').str.to_lowercase().str.contains(song_input_prepped))
     .with_columns(pl.col('pair').str.split(' --- '))
     .sort('times_played_together',
           pl.col('owner.display_name').list.len(), 
           descending=True)
     .head(100).collect()
    )
    
    
    
    
    
    st.markdown(f"#### Most common songs to play after _{song_input}_:")
    
    st.dataframe(df
     .select('song_number', 'track.name', 'playlist_name', 'track.id', 'playlist_id', 'owner.display_name')
     .unique()
     .sort('playlist_id', 'song_number')
     
     .with_columns(pair1 = pl.when(pl.col('song_number').shift(-1) > pl.col('song_number'))
                            .then(pl.concat_str(pl.col('track.name'), pl.lit(': '), pl.col('track.id'), pl.lit(' --- '),
                                                pl.col('track.name').shift(-1), pl.lit(': '), pl.col('track.id').shift(-1),
                                                )),
                   pair2 = pl.when(pl.col('song_number').shift(1) < pl.col('song_number'))
                            .then(pl.concat_str(pl.col('track.name').shift(-1), pl.lit(': '), pl.col('track.id').shift(1), pl.lit(' --- '),
                                                pl.col('track.name'), pl.lit(': '), pl.col('track.id'),
                                                )),
                  )
     .with_columns(pair = pl.concat_list('pair1', 'pair2'))
     .explode('pair')
     .select('pair', 'playlist_name', 'owner.display_name'
            )
     .drop_nulls()
     .unique()
     .with_columns(pl.col('pair').str.split(' --- ').list.sort().list.join(' --- '))
     .group_by('pair')
     .agg(pl.n_unique('playlist_name').alias('times_played_together'), 'playlist_name', 'owner.display_name',)
     .with_columns(pl.col('playlist_name').list.unique(),
                  pl.col('owner.display_name').list.unique())
     .filter(~pl.col('playlist_name').list.join(', ').str.contains_any(['The Maine', 'delete', 'SPOTIFY']),
            pl.col('times_played_together').gt(1),
            )
     .filter(pl.col('pair').str.split(' --- ').list.get(0).str.to_lowercase().str.contains(song_input_prepped))
     .with_columns(pl.col('pair').str.split(' --- '))
     .sort('times_played_together',
           pl.col('owner.display_name').list.len(), 
           descending=True)
     .head(100).collect()
    )
    
    
    
    st.markdown(f"#### Most common songs to play before _{song_input}_:")
    
    st.dataframe(df
     .select('song_number', 'track.name', 'playlist_name', 'track.id', 'playlist_id', 'owner.display_name')
     .unique()
     .sort('playlist_id', 'song_number')
     
     .with_columns(pair1 = pl.when(pl.col('song_number').shift(-1) > pl.col('song_number'))
                            .then(pl.concat_str(pl.col('track.name'), pl.lit(': '), pl.col('track.id'), pl.lit(' --- '),
                                                pl.col('track.name').shift(-1), pl.lit(': '), pl.col('track.id').shift(-1),
                                                )),
                   pair2 = pl.when(pl.col('song_number').shift(1) < pl.col('song_number'))
                            .then(pl.concat_str(pl.col('track.name').shift(-1), pl.lit(': '), pl.col('track.id').shift(1), pl.lit(' --- '),
                                                pl.col('track.name'), pl.lit(': '), pl.col('track.id'),
                                                )),
                  )
     .with_columns(pair = pl.concat_list('pair1', 'pair2'))
     .explode('pair')
     .select('pair', 'playlist_name', 'owner.display_name'
            )
     .drop_nulls()
     .unique()
     .with_columns(pl.col('pair').str.split(' --- ').list.sort().list.join(' --- '))
     .group_by('pair')
     .agg(pl.n_unique('playlist_name').alias('times_played_together'), 'playlist_name', 'owner.display_name',)
     .with_columns(pl.col('playlist_name').list.unique(),
                  pl.col('owner.display_name').list.unique())
     .filter(~pl.col('playlist_name').list.join(', ').str.contains_any(['The Maine', 'delete', 'SPOTIFY']),
            pl.col('times_played_together').gt(1),
            )
     .filter(pl.col('pair').str.split(' --- ').list.get(1).str.to_lowercase().str.contains(song_input_prepped))
     .with_columns(pl.col('pair').str.split(' --- '))
     .sort('times_played_together',
           pl.col('owner.display_name').list.len(), 
           descending=True)
     .head(100).collect()
    )
























st.markdown("# ")



#courtesy of Lino V
st.markdown(f"\n\n\n## Geographic Region Music:")

region_selectbox = st.selectbox("Which Geographic Region would you like to see?",
                                ["Europe", "USA", "Asia", "MENA"])


st.markdown(f"#### What are the most popular songs only played in {region_selectbox}?")
europe = (df
          #  .pipe(wcs_specific)
          .filter(pl.col('regions') == region_selectbox)
          .select('song', 'dj_count', 'playlist_count', 'regions', 'geographic_region_count')
          .unique()
          .sort('dj_count', descending=True)
          )

st.dataframe(europe.head(100).collect(streaming=True))
















st.text("\n\nIf you have questions/feedback/suggestions, please leave a comment: \nhttps://forms.gle/19mALUpmM9Z5XCA28")
