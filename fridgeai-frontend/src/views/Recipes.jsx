import { useEffect, useState } from 'react'
import { C } from '../constants.js'
import { api } from '../api.js'
import RecipeUploadModal from '../components/RecipeUploadModal.jsx'

export default function Recipes() {
  const [recipes, setRecipes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showUpload, setShowUpload] = useState(false)

  const loadRecipes = async () => {
    try {
      setLoading(true)
      const data = await api.getRecipes()
      if (data && !data.error) {
        setRecipes(data)
      } else {
        setError(data.error || 'Failed to fetch recipes')
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRecipes()
  }, [])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0', color: C.muted }}>
        <div style={{ fontSize: 40, marginBottom: 12, animation: 'spin 2s linear infinite' }}>🥘</div>
        <div style={{ fontSize: 16 }}>Curating Recipes for You…</div>
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0', color: C.critical }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>⚠️</div>
        <div style={{ fontSize: 16 }}>{error}</div>
      </div>
    )
  }

  if (!recipes || recipes.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0', color: C.muted }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>👨‍🍳</div>
        <div style={{ fontSize: 16 }}>No recipes found.</div>
        <div style={{ fontSize: 14, marginTop: 6 }}>Try adding more items to your fridge!</div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h2 style={{ fontSize: 26, fontWeight: 700, color: C.text, margin: 0, letterSpacing: '-0.02em' }}>Smart Recipes</h2>
          <p style={{ color: C.muted, fontSize: 15, marginTop: 6, margin: 0 }}>
            Delicious meals based on what's currently in your FridgeAI inventory.
          </p>
        </div>
        <button className="glass-button-primary" onClick={() => setShowUpload(true)} style={{ padding: '10px 20px', fontSize: 14 }}>
          + Upload Recipe
        </button>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
        gap: 20,
      }}>
        {recipes.map(recipe => (
          <RecipeCard key={recipe.id} recipe={recipe} />
        ))}
      </div>
    </div>
  )
}

function RecipeCard({ recipe }) {
  const usedCount = recipe.usedIngredientCount || 0
  const missedCount = recipe.missedIngredientCount || 0
  const totalCount = usedCount + missedCount
  
  // calculate a match percentage
  const matchPercent = totalCount > 0 ? Math.round((usedCount / totalCount) * 100) : 0

  return (
    <div className="glass-card" style={{
      display: 'flex', flexDirection: 'column', overflow: 'hidden', cursor: 'pointer'
    }}>
      <div style={{ position: 'relative', height: 180, background: 'rgba(0,0,0,0.3)', borderBottom: `1px solid rgba(255,255,255,0.05)` }}>
        {recipe.image && (
          <img src={recipe.image} alt={recipe.title} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        )}
        <div style={{
          position: 'absolute', top: 12, right: 12, background: C.bg,
          color: matchPercent >= 80 ? C.safe : matchPercent >= 50 ? C.warn : C.critical,
          padding: '4px 10px', borderRadius: 20, fontSize: 12, fontWeight: 700,
          boxShadow: '0 2px 8px rgba(0,0,0,0.2)'
        }}>
          {matchPercent}% Match
        </div>
      </div>
      
      <div style={{ padding: 20, flex: 1, display: 'flex', flexDirection: 'column' }}>
        <h3 style={{ fontSize: 18, fontWeight: 700, color: C.text, margin: '0 0 12px 0', lineHeight: 1.3 }}>
          {recipe.title}
        </h3>
        
        <div style={{ flex: 1 }}>
          {usedCount > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: C.safe, marginBottom: 4, textTransform: 'uppercase' }}>
                You Have ({usedCount})
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {recipe.usedIngredients?.map(i => (
                  <span key={i.id} style={{ background: C.safe + '15', color: C.safe, padding: '2px 8px', borderRadius: 12, fontSize: 12 }}>
                    {i.name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {missedCount > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: C.critical, marginBottom: 4, textTransform: 'uppercase' }}>
                You Need ({missedCount})
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {recipe.missedIngredients?.slice(0, 5).map(i => (
                  <span key={i.id} style={{ background: C.critical + '15', color: C.critical, padding: '2px 8px', borderRadius: 12, fontSize: 12 }}>
                    {i.name}
                  </span>
                ))}
                {missedCount > 5 && <span style={{ color: C.muted, fontSize: 12 }}>+{missedCount - 5} more</span>}
              </div>
            </div>
          )}
        </div>
        
        
        <button className="glass-button" style={{
          marginTop: 20, width: '100%', padding: '10px 0',
          color: C.teal, fontSize: 14, fontWeight: 700
        }}>
          View Recipe
        </button>
      </div>
    </div>
  )
}
