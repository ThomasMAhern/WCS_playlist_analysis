import streamlit as st
import polars as pl

pl.Config.set_tbl_rows(100).set_fmt_str_lengths(100)

regex_year_first = r'\d{2,4}[.\-/ ]?\d{1,2}[.\-/ ]?\d{1,2}'
regex_year_last = r'\d{1,2}[.\-/ ]?\d{1,2}[.\-/ ]?\d{2,4}'
regex_year_abbreviated = r"'\d{2}"

def wcs_specific(df_):
  '''given a df, filter to the records most likely to be west coast swing related'''
  return (df_
          .filter(~(pl.col('name').str.contains(regex_year_first)
                  |pl.col('name').str.contains(regex_year_last)
                  |pl.col('name').str.contains(regex_year_abbreviated)
                  |pl.col('name').str.to_lowercase().str.contains('wcs|social|party|oirée|west coast|routine|blues|practice|practise|bpm|swing|novice|intermediate|comp|musicality|timing|pro show')))
      )

df = (pl.read_parquet('wcs_dj_spotify_playlists.parquet')

      #makes a new column filled with a date - this is good indicator if there was a set played
      .with_columns(extracted_date = pl.concat_list(pl.col('name').str.extract_all(regex_year_last),
                                                    pl.col('name').str.extract_all(regex_year_last),
                                                    pl.col('name').str.extract_all(regex_year_abbreviated),)
                                       .list.unique().list.sort(),
                    song = pl.concat_str('track.name', pl.lit(' - https://open.spotify.com/track/'), 'track.id', ignore_nulls=True),
                    region = pl.col('location').str.split(' - ').list.get(0),)
      
      #gets the counts of djs, playlists, and geographic regions a song is found in
      .with_columns(num_djs = pl.n_unique('owner.display_name').over(pl.col('song')),
                    num_playlists = pl.n_unique('name').over(pl.col('song')),
                    num_regions = pl.n_unique('region').over('song'),
                    regions = pl.col('region').over('song', mapping_strategy='join')
                                  .list.unique()
                                  .list.drop_nulls()
                                  .list.sort()
                                  .list.join(', '),)
      )

st.write(f"{df.select(pl.concat_str('track.name', pl.lit(' - '), 'track.id')).unique().shape[0]:,} Songs ({df.pipe(wcs_specific).select(pl.concat_str('track.name', pl.lit(' - '), 'track.id')).unique().shape[0]:,} wcs specific)")

st.write(f"{df.select('track.artists.id').unique().shape[0]:,} Artists ({df.pipe(wcs_specific).select('track.artists.id').unique().shape[0]:,} wcs specific)")

st.write(f"{df.select('name').unique().shape[0]:,} Playlists ({df.pipe(wcs_specific).select('name').unique().shape[0]:,} wcs specific)\n\n")




st.dataframe(df.sample(100))