import google.generativeai as genai
import os
from typing import List, Optional
from models import ChatMessage, Product, NegotiationApproach
import json
import asyncio


class GeminiAIService:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
        self.setup_client()
        
    def setup_client(self):
        """Setup Gemini AI client"""
        try:
            genai.configure(api_key=self.api_key)
            # Use the correct model name for current Gemini API
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            print("✅ Gemini AI service initialized")
        except Exception as e:
            print(f"❌ Failed to initialize Gemini AI: {e}")
            self.model = None
    
    async def generate_response(
        self,
        approach,  # Can be string or NegotiationApproach enum
        target_price: int,
        max_budget: int,
        chat_history: List[ChatMessage],
        product: Product
    ) -> str:
        """Generate AI response based on negotiation context"""
        
        # Convert string to enum if needed
        if isinstance(approach, str):
            try:
                approach = NegotiationApproach(approach.lower())
            except ValueError:
                approach = NegotiationApproach.DIPLOMATIC  # Default fallback
        
        if not self.model:
            return self._get_fallback_response(approach, target_price, chat_history, product)
        
        try:
            # Build context for AI
            context = self._build_negotiation_context(
                approach, target_price, max_budget, chat_history, product
            )
            
            # Generate response using Gemini
            response = await self._call_gemini_api(context)
            return response
            
        except Exception as e:
            print(f"Error generating AI response: {e}")
            return self._get_fallback_response(approach, target_price, chat_history)
    
    def _build_negotiation_context(
        self,
        approach: NegotiationApproach,
        target_price: int,
        max_budget: int,
        chat_history: List[ChatMessage],
        product: Product
    ) -> str:
        """Build context prompt for Gemini AI"""
        
        # Get the latest seller message
        seller_messages = [msg for msg in chat_history if msg.sender == "seller"]
        last_seller_message = seller_messages[-1].content if seller_messages else ""
        
        # Build conversation history
        conversation_history = ""
        for msg in chat_history[-6:]:  # Last 6 messages for context
            sender_label = "Seller" if msg.sender == "seller" else "You (Buyer)"
            conversation_history += f"{sender_label}: {msg.content}\n"
        
        # Define approach strategies
        approach_strategies = {
            NegotiationApproach.ASSERTIVE: {
                "style": "direct and confident",
                "tactics": "Make firm offers, emphasize market research, be persistent but polite",
                "personality": "business-like and decisive"
            },
            NegotiationApproach.DIPLOMATIC: {
                "style": "balanced and respectful",
                "tactics": "Find mutual benefits, acknowledge seller's position, propose win-win solutions",
                "personality": "professional and understanding"
            },
            NegotiationApproach.CONSIDERATE: {
                "style": "empathetic and budget-conscious",
                "tactics": "Explain budget constraints, show genuine interest, be patient",
                "personality": "humble and appreciative"
            }
        }
        
        strategy = approach_strategies.get(approach, approach_strategies[NegotiationApproach.DIPLOMATIC])
        
        prompt = f"""
You are an AI negotiation agent representing a buyer who wants to purchase: {product.title}

PRODUCT DETAILS:
- Current asking price: ₹{product.price:,}
- Your target price: ₹{target_price:,}
- Your maximum budget: ₹{max_budget:,}
- Product condition: {product.condition}
- Seller: {product.seller_name}
- Location: {product.location}

NEGOTIATION APPROACH: {approach.value.upper()}
- Style: {strategy["style"]}
- Tactics: {strategy["tactics"]}
- Personality: {strategy["personality"]}

CONVERSATION HISTORY:
{conversation_history}

LATEST SELLER MESSAGE: "{last_seller_message}"

INSTRUCTIONS:
1. Respond as a human buyer (never mention you're an AI)
2. Use the {approach.value} negotiation approach consistently
3. Stay within your budget constraints (max ₹{max_budget:,})
4. Work towards your target price of ₹{target_price:,}
5. Keep responses conversational and natural (50-80 words)
6. Include relevant details about pickup/payment when appropriate
7. Be respectful but persistent in negotiations
8. If the seller's price is too high, explain your position clearly
9. If a good deal is reached, move towards closing (exchange contact details)

CURRENT SITUATION ANALYSIS:
- Current offer/price being discussed: Look at the conversation
- Progress towards target: Calculate if you're getting closer
- Seller's flexibility: Assess from their responses

Generate your next response as the buyer:
"""
        
        return prompt
    
    async def _call_gemini_api(self, prompt: str) -> str:
        """Call Gemini API asynchronously"""
        try:
            # Run the synchronous Gemini call in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: self.model.generate_content(prompt)
            )
            
            return response.text.strip()
            
        except Exception as e:
            print(f"Gemini API error: {e}")
            raise
    
    def _get_fallback_response(
        self, 
        approach,  # Can be string or NegotiationApproach enum
        target_price: int, 
        chat_history: List[ChatMessage],
        product: Product
    ) -> str:
        """Fallback responses when AI is not available"""
        
        # Convert string to enum if needed
        if isinstance(approach, str):
            try:
                approach = NegotiationApproach(approach.lower())
            except ValueError:
                approach = NegotiationApproach.DIPLOMATIC  # Default fallback
        
        # Get last seller message
        seller_messages = [msg for msg in chat_history if msg.sender == "seller"]
        
        if not seller_messages:
            # Opening message
            if approach == NegotiationApproach.ASSERTIVE:
                return f"Hello {product.seller_name}! I'm interested in your listing. Based on current market rates, I'd like to offer ₹{target_price:,}. Is this acceptable?"
            elif approach == NegotiationApproach.DIPLOMATIC:
                return f"Good day {product.seller_name}! I'm very interested in your product. Would you consider an offer of ₹{target_price:,}? I believe it's a fair price given the current market."
            else:  # CONSIDERATE
                return f"Hi {product.seller_name}! I'm really interested in your listing. My budget is a bit tight at ₹{target_price:,}. Would this work for you?"
        
        # Response to seller
        last_message = seller_messages[-1].content.lower()
        message_count = len(seller_messages)
        
        # Keywords for different responses
        if "hi" in last_message or "hello" in last_message or "available" in last_message:
            # Greeting/availability check
            if approach == NegotiationApproach.ASSERTIVE:
                return f"Hello {product.seller_name}! Yes, I'm very interested. I can offer ₹{target_price:,} for immediate purchase. When can we meet?"
            elif approach == NegotiationApproach.DIPLOMATIC:
                return f"Hi there {product.seller_name}! Yes, I'm interested in your listing. The item looks great. Would ₹{target_price:,} work for you?"
            else:  # CONSIDERATE
                return f"Hello {product.seller_name}! Yes, I'm interested. I'm hoping to stay within ₹{target_price:,} if possible. Could we work something out?"
        
        elif "price" in last_message or "cost" in last_message or "amount" in last_message:
            # Price discussion
            if approach == NegotiationApproach.ASSERTIVE:
                return f"Based on market research, ₹{target_price:,} is what I can offer. It's competitive and fair."
            elif approach == NegotiationApproach.DIPLOMATIC:
                return f"I've been looking at similar items, and ₹{target_price:,} seems reasonable. What do you think?"
            else:  # CONSIDERATE
                return f"I understand the value, but my budget is limited to ₹{target_price:,}. Is there any flexibility?"
        
        elif "no" in last_message or "cannot" in last_message or "firm" in last_message or "minimum" in last_message:
            # Seller rejected - increase offer slightly
            counter_offer = min(int(target_price * 1.15), target_price + 5000)
            if approach == NegotiationApproach.ASSERTIVE:
                return f"I understand. Let me stretch my budget to ₹{counter_offer:,}. This is really my maximum."
            elif approach == NegotiationApproach.DIPLOMATIC:
                return f"I appreciate your position. Could we perhaps meet at ₹{counter_offer:,}? That would really help both of us."
            else:  # CONSIDERATE
                return f"I really want this item. Could you please consider ₹{counter_offer:,}? It would mean a lot to me."
        
        elif "yes" in last_message or "okay" in last_message or "accept" in last_message or "deal" in last_message:
            # Seller accepted
            return "Excellent! That works perfectly for me. When would be convenient for pickup? I can arrange payment immediately."
        
        elif "meet" in last_message or "pickup" in last_message or "delivery" in last_message:
            # Logistics discussion
            return "Perfect! I'm flexible with timing. I can come today or tomorrow, whatever works best for you. Should I bring cash or is online transfer preferred?"
        
        elif "condition" in last_message or "working" in last_message or "problem" in last_message:
            # Product condition inquiry
            return "Thank you for the details. As long as everything is as described, I'm happy to proceed with ₹{target_price:,}. Can we finalize this?"
        
        else:
            # General response
            if approach == NegotiationApproach.ASSERTIVE:
                return f"Let me be direct - I can offer ₹{target_price:,} and arrange pickup today. This is a fair market price."
            elif approach == NegotiationApproach.DIPLOMATIC:
                return f"I've researched similar listings and ₹{target_price:,} seems to be the going rate. Would you consider this offer?"
            else:  # CONSIDERATE
                return f"I'm really hoping we can work something out at ₹{target_price:,}. This would really help with my budget constraints."


# Utility function to test Gemini API connection
async def test_gemini_connection():
    """Test function to verify Gemini API is working"""
    service = GeminiAIService()
    
    if not service.model:
        print("❌ Gemini API not configured properly")
        return False
    
    try:
        test_prompt = "Say 'Hello from Gemini AI!' in a friendly way."
        response = await service._call_gemini_api(test_prompt)
        print(f"✅ Gemini API test successful: {response}")
        return True
    except Exception as e:
        print(f"❌ Gemini API test failed: {e}")
        return False